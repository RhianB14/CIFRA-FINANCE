from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction


@dataclass(frozen=True, slots=True)
class CurrencyBalance:
    currency: str
    posted_balance_cents: int
    projected_balance_cents: int


@dataclass(frozen=True, slots=True)
class AccountBalanceView:
    account_id: UUID
    name: str
    currency: str
    kind: str
    posted_balance_cents: int
    projected_balance_cents: int


@dataclass(frozen=True, slots=True)
class MonthFlow:
    currency: str
    month: str
    income_cents: int
    expense_cents: int
    net_cents: int


@dataclass(frozen=True, slots=True)
class UpcomingView:
    id: UUID
    account_id: UUID
    operation_type: str
    amount_cents: int
    occurred_at: datetime
    description: str | None


@dataclass(frozen=True, slots=True)
class RecentView:
    id: UUID
    account_id: UUID
    operation_type: str
    status: str
    amount_cents: int
    occurred_at: datetime
    description: str | None


@dataclass(frozen=True, slots=True)
class EvolutionPoint:
    currency: str
    month: str
    income_cents: int
    expense_cents: int
    end_balance_cents: int


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    currency: str
    current_income_cents: int
    current_expense_cents: int
    current_net_cents: int
    previous_income_cents: int
    previous_expense_cents: int
    previous_net_cents: int
    delta_income_cents: int
    delta_expense_cents: int
    delta_net_cents: int


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    month: str
    generated_at: datetime
    consolidated_by_currency: list[CurrencyBalance]
    month_flow: list[MonthFlow]
    accounts: list[AccountBalanceView]
    upcoming: list[UpcomingView]
    recent: list[RecentView]


@dataclass(frozen=True, slots=True)
class DashboardComparison:
    current_month: str
    previous_month: str
    rows: list[ComparisonRow]


class DashboardError(Exception):
    pass


def parse_month(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).strftime("%Y-%m")
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise DashboardError("month must use YYYY-MM format")
    if not parts[0].isdigit() or not parts[1].isdigit():
        raise DashboardError("month must use YYYY-MM format")
    year = int(parts[0])
    month = int(parts[1])
    if month < 1 or month > 12:
        raise DashboardError("month must use YYYY-MM format")
    return f"{year:04d}-{month:02d}"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    year = int(month[:4])
    month_index = int(month[5:7])
    start = datetime(year, month_index, 1, tzinfo=UTC)
    if month_index == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month_index + 1, 1, tzinfo=UTC)
    return start, end


def previous_month(month: str) -> str:
    year = int(month[:4])
    month_index = int(month[5:7])
    if month_index == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month_index - 1:02d}"


def month_range(month: str, months: int) -> list[str]:
    year = int(month[:4])
    month_index = int(month[5:7])
    result = []
    for offset in range(months - 1, -1, -1):
        total = year * 12 + (month_index - 1) - offset
        result.append(f"{total // 12:04d}-{total % 12 + 1:02d}")
    return result


def _signed(kind: str, amount: int) -> int:
    return amount if kind == "credit" else -amount


async def _user_accounts(
    session: AsyncSession,
    user_id: UUID,
    include_archived: bool = False,
) -> list[Account]:
    conditions = [Account.user_id == user_id]
    if not include_archived:
        conditions.append(Account.archived_at.is_(None))
    rows = await session.execute(
        select(Account).where(*conditions).order_by(Account.created_at, Account.id)
    )
    return list(rows.scalars().all())


async def _flows_per_account(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    account_ids: set[UUID] | None = None,
) -> dict[UUID, tuple[int, int]]:
    conditions = [
        Transaction.user_id == user_id,
        Transaction.status == "posted",
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end,
        Transaction.operation_type.notin_(("transfer_out", "transfer_in")),
    ]
    if account_ids is not None:
        conditions.append(Transaction.account_id.in_(account_ids))
    rows = await session.execute(
        select(
            Transaction.account_id,
            Transaction.kind,
            func.sum(Transaction.amount_cents),
        )
        .where(*conditions)
        .group_by(Transaction.account_id, Transaction.kind)
    )
    buckets: dict[UUID, list[int]] = {}
    for account_id, kind, total in rows.all():
        slot = buckets.setdefault(account_id, [0, 0])
        if kind == "credit":
            slot[0] += int(total)
        else:
            slot[1] += int(total)
    return {account_id: (slot[0], slot[1]) for account_id, slot in buckets.items()}


async def _flows_per_currency(
    session: AsyncSession,
    user_id: UUID,
    start: datetime,
    end: datetime,
    account_ids: set[UUID] | None = None,
) -> dict[str, tuple[int, int]]:
    conditions = [
        Transaction.user_id == user_id,
        Transaction.status == "posted",
        Transaction.occurred_at >= start,
        Transaction.occurred_at < end,
        Transaction.operation_type.notin_(("transfer_out", "transfer_in")),
    ]
    if account_ids is not None:
        conditions.append(Transaction.account_id.in_(account_ids))
    rows = await session.execute(
        select(
            Account.currency,
            Transaction.kind,
            func.sum(Transaction.amount_cents),
        )
        .join(Account, Account.id == Transaction.account_id)
        .where(*conditions)
        .group_by(Account.currency, Transaction.kind)
    )
    buckets: dict[str, list[int]] = {}
    for currency, kind, total in rows.all():
        slot = buckets.setdefault(currency, [0, 0])
        if kind == "credit":
            slot[0] += int(total)
        else:
            slot[1] += int(total)
    return {currency: (slot[0], slot[1]) for currency, slot in buckets.items()}


async def _pending_per_account(
    session: AsyncSession,
    user_id: UUID,
) -> dict[UUID, int]:
    rows = await session.execute(
        select(Transaction.account_id, Transaction.kind, func.sum(Transaction.amount_cents))
        .where(
            Transaction.user_id == user_id,
            Transaction.status == "pending",
        )
        .group_by(Transaction.account_id, Transaction.kind)
    )
    totals: dict[UUID, int] = {}
    for account_id, kind, total in rows.all():
        totals[account_id] = totals.get(account_id, 0) + _signed(kind, int(total))
    return totals


async def dashboard_summary(
    session: AsyncSession,
    user_id: UUID,
    month: str,
) -> DashboardSummary:
    month_start, month_end = month_bounds(month)
    accounts = await _user_accounts(session, user_id)
    active_ids = {account.id for account in accounts}
    flows = await _flows_per_account(
        session, user_id, month_start, month_end, account_ids=active_ids
    )
    pending = await _pending_per_account(session, user_id)

    currency_posted: dict[str, int] = {}
    currency_projected: dict[str, int] = {}
    account_views: list[AccountBalanceView] = []
    for account in accounts:
        posted = account.current_balance_cents
        projected = posted + pending.get(account.id, 0)
        account_views.append(
            AccountBalanceView(
                account_id=account.id,
                name=account.name,
                currency=account.currency,
                kind=account.kind,
                posted_balance_cents=posted,
                projected_balance_cents=projected,
            )
        )
        currency_posted[account.currency] = currency_posted.get(account.currency, 0) + posted
        currency_projected[account.currency] = (
            currency_projected.get(account.currency, 0) + projected
        )

    consolidated = [
        CurrencyBalance(
            currency=currency,
            posted_balance_cents=currency_posted[currency],
            projected_balance_cents=currency_projected[currency],
        )
        for currency in sorted(currency_posted)
    ]

    currency_by_account = {account.id: account.currency for account in accounts}
    flow_income: dict[str, int] = {}
    flow_expense: dict[str, int] = {}
    for account_id, (income, expense) in flows.items():
        currency = currency_by_account[account_id]
        flow_income[currency] = flow_income.get(currency, 0) + income
        flow_expense[currency] = flow_expense.get(currency, 0) + expense
    month_flow = [
        MonthFlow(
            currency=currency,
            month=month,
            income_cents=flow_income.get(currency, 0),
            expense_cents=flow_expense.get(currency, 0),
            net_cents=flow_income.get(currency, 0) - flow_expense.get(currency, 0),
        )
        for currency in sorted({account.currency for account in accounts})
    ]

    upcoming_rows = await session.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.status == "pending")
        .order_by(Transaction.occurred_at, Transaction.created_at)
        .limit(10)
    )
    upcoming = [
        UpcomingView(
            id=row.id,
            account_id=row.account_id,
            operation_type=row.operation_type,
            amount_cents=row.amount_cents,
            occurred_at=row.occurred_at,
            description=row.description,
        )
        for row in upcoming_rows.scalars()
    ]

    recent_rows = await session.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.status == "posted")
        .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
        .limit(10)
    )
    recent = [
        RecentView(
            id=row.id,
            account_id=row.account_id,
            operation_type=row.operation_type,
            status=row.status,
            amount_cents=row.amount_cents,
            occurred_at=row.occurred_at,
            description=row.description,
        )
        for row in recent_rows.scalars()
    ]

    return DashboardSummary(
        month=month,
        generated_at=datetime.now(UTC),
        consolidated_by_currency=consolidated,
        month_flow=month_flow,
        accounts=account_views,
        upcoming=upcoming,
        recent=recent,
    )


async def dashboard_evolution(
    session: AsyncSession,
    user_id: UUID,
    months: int,
    until: str,
) -> list[EvolutionPoint]:
    series = month_range(until, months)
    window_start = month_bounds(series[0])[0]

    accounts = await _user_accounts(session, user_id)
    active_ids = {account.id for account in accounts}

    pre_flows = await _flows_per_currency(
        session, user_id, datetime(1970, 1, 1, tzinfo=UTC), window_start, account_ids=active_ids
    )

    opening: dict[str, int] = {}
    for account in accounts:
        opening[account.currency] = opening.get(account.currency, 0) + account.initial_balance_cents

    points: list[EvolutionPoint] = []

    def _transfer_signed(kind: str, amount: int) -> int:
        return amount if kind == "credit" else -amount

    async def _transfer_net_per_currency(
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        rows = await session.execute(
            select(
                Account.currency,
                Transaction.kind,
                func.sum(Transaction.amount_cents),
            )
            .join(Account, Account.id == Transaction.account_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.status == "posted",
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
                Transaction.operation_type.in_(("transfer_out", "transfer_in")),
                Transaction.account_id.in_(active_ids),
            )
            .group_by(Account.currency, Transaction.kind)
        )
        nets: dict[str, int] = {}
        for currency, kind, total in rows.all():
            nets[currency] = nets.get(currency, 0) + _transfer_signed(kind, int(total))
        return nets

    for currency in sorted(opening):
        pre_income, pre_expense = pre_flows.get(currency, (0, 0))
        running = opening[currency] + pre_income - pre_expense
        for month_label in series:
            month_start, month_end = month_bounds(month_label)
            month_flow = await _flows_per_currency(
                session, user_id, month_start, month_end, account_ids=active_ids
            )
            income, expense = month_flow.get(currency, (0, 0))
            transfer_month = await _transfer_net_per_currency(month_start, month_end)
            running += income - expense
            running += transfer_month.get(currency, 0)
            points.append(
                EvolutionPoint(
                    currency=currency,
                    month=month_label,
                    income_cents=income,
                    expense_cents=expense,
                    end_balance_cents=running,
                )
            )
    return points


async def dashboard_month_comparison(
    session: AsyncSession,
    user_id: UUID,
    month: str,
) -> DashboardComparison:
    previous = previous_month(month)
    current_start, current_end = month_bounds(month)
    previous_start, previous_end = month_bounds(previous)

    accounts = await _user_accounts(session, user_id)
    active_ids = {account.id for account in accounts}
    current_flows = await _flows_per_currency(
        session, user_id, current_start, current_end, account_ids=active_ids
    )
    previous_flows = await _flows_per_currency(
        session, user_id, previous_start, previous_end, account_ids=active_ids
    )

    rows: list[ComparisonRow] = []
    for currency in sorted(set(current_flows) | set(previous_flows)):
        current_income, current_expense = current_flows.get(currency, (0, 0))
        previous_income, previous_expense = previous_flows.get(currency, (0, 0))
        current_net = current_income - current_expense
        previous_net = previous_income - previous_expense
        rows.append(
            ComparisonRow(
                currency=currency,
                current_income_cents=current_income,
                current_expense_cents=current_expense,
                current_net_cents=current_net,
                previous_income_cents=previous_income,
                previous_expense_cents=previous_expense,
                previous_net_cents=previous_net,
                delta_income_cents=current_income - previous_income,
                delta_expense_cents=current_expense - previous_expense,
                delta_net_cents=current_net - previous_net,
            )
        )
    return DashboardComparison(
        current_month=month,
        previous_month=previous,
        rows=rows,
    )
