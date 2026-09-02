import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, RecurringTransaction

_CADENCES = ("daily", "weekly", "monthly", "yearly")
_OPERATIONS = ("deposit", "withdrawal")


@dataclass(frozen=True, slots=True)
class RecurringCreated:
    id: UUID
    user_id: UUID
    account_id: UUID
    template_operation_type: str
    template_amount_cents: int
    template_description: str | None
    recurrence: str
    starts_on: date
    ends_on: date | None
    next_run_on: date
    is_active: bool


class RecurringError(Exception):
    pass


def advance_date(anchor: date, recurrence: str, steps: int) -> date:
    if steps < 0:
        raise RecurringError("steps must not be negative")
    if recurrence == "daily":
        return anchor + timedelta(days=steps)
    if recurrence == "weekly":
        return anchor + timedelta(weeks=steps)
    if recurrence == "monthly":
        month_index = anchor.year * 12 + (anchor.month - 1) + steps
        year = month_index // 12
        month = month_index % 12 + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    if recurrence == "yearly":
        year = anchor.year + steps
        day = min(anchor.day, calendar.monthrange(year, anchor.month)[1])
        return date(year, anchor.month, day)
    raise RecurringError("unsupported cadence")


async def create_recurring(
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    template_operation_type: str,
    template_amount_cents: int,
    recurrence: str,
    starts_on: date,
    ends_on: date | None = None,
    template_description: str | None = None,
) -> RecurringCreated:
    if recurrence not in _CADENCES:
        raise RecurringError("unsupported cadence")
    if template_operation_type not in _OPERATIONS:
        raise RecurringError("unsupported template operation type")
    if template_amount_cents <= 0:
        raise RecurringError("template amount must be positive")
    if ends_on is not None and ends_on < starts_on:
        raise RecurringError("ends_on must not precede starts_on")

    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise RecurringError("account not found for owner")

    row = RecurringTransaction(
        user_id=user_id,
        account_id=account_id,
        template_operation_type=template_operation_type,
        template_amount_cents=template_amount_cents,
        template_description=template_description,
        recurrence=recurrence,
        starts_on=starts_on,
        ends_on=ends_on,
        next_run_on=starts_on,
        is_active=True,
    )
    session.add(row)
    await session.flush()
    return RecurringCreated(
        id=row.id,
        user_id=row.user_id,
        account_id=row.account_id,
        template_operation_type=row.template_operation_type,
        template_amount_cents=row.template_amount_cents,
        template_description=row.template_description,
        recurrence=row.recurrence,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        next_run_on=row.next_run_on,
        is_active=row.is_active,
    )


def _recurring_to_created(row: RecurringTransaction) -> RecurringCreated:
    return RecurringCreated(
        id=row.id,
        user_id=row.user_id,
        account_id=row.account_id,
        template_operation_type=row.template_operation_type,
        template_amount_cents=row.template_amount_cents,
        template_description=row.template_description,
        recurrence=row.recurrence,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        next_run_on=row.next_run_on,
        is_active=row.is_active,
    )


async def get_recurring(
    session: AsyncSession, user_id: UUID, recurring_id: UUID
) -> RecurringCreated:
    row = await session.get(RecurringTransaction, recurring_id)
    if row is None or row.user_id != user_id:
        raise RecurringError("recurring transaction not found")
    return _recurring_to_created(row)


async def list_recurring(session: AsyncSession, user_id: UUID) -> list[RecurringCreated]:
    rows = await session.execute(
        select(RecurringTransaction)
        .where(RecurringTransaction.user_id == user_id)
        .order_by(RecurringTransaction.next_run_on, RecurringTransaction.created_at)
    )
    return [_recurring_to_created(r) for r in rows.scalars()]


async def update_recurring(
    session: AsyncSession,
    user_id: UUID,
    recurring_id: UUID,
    updates: dict[str, object],
) -> RecurringCreated:
    row = await session.get(RecurringTransaction, recurring_id)
    if row is None or row.user_id != user_id:
        raise RecurringError("recurring transaction not found")

    allowed = {"template_description", "is_active", "ends_on"}
    for key, value in updates.items():
        if key not in allowed:
            raise RecurringError("field not updatable")
        setattr(row, key, value)
    if row.ends_on is not None and row.ends_on < row.starts_on:
        raise RecurringError("ends_on must not precede starts_on")
    await session.flush()
    return _recurring_to_created(row)


async def delete_recurring(session: AsyncSession, user_id: UUID, recurring_id: UUID) -> None:
    row = await session.get(RecurringTransaction, recurring_id)
    if row is None or row.user_id != user_id:
        raise RecurringError("recurring transaction not found")
    await session.delete(row)
