import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, RecurringTransaction, Transaction
from app.services.ledger import IdempotencyConflictError

_CADENCES = ("daily", "weekly", "monthly", "yearly")
_OPERATIONS = ("deposit", "withdrawal")

_OCCURRENCE_TIME = (12, 0, 0)


@dataclass(frozen=True, slots=True)
class MaterializeResult:
    created: int
    replayed: int
    paused: int


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


async def materialize_recurring(
    session: AsyncSession,
    user_id: UUID,
    today: date,
) -> MaterializeResult:
    accounts = await session.execute(select(Account.id).where(Account.user_id == user_id))
    account_ids = [row[0] for row in accounts.all()]
    if not account_ids:
        raise RecurringError("account not found for owner")

    rows = await session.execute(
        select(RecurringTransaction)
        .where(
            RecurringTransaction.user_id == user_id,
            RecurringTransaction.account_id.in_(account_ids),
        )
        .order_by(RecurringTransaction.next_run_on)
    )
    created = 0
    replayed = 0
    paused = 0
    for row in rows.scalars():
        if not row.is_active:
            paused += 1
            continue
        if row.next_run_on > today:
            continue
        step = 0
        while True:
            occurrence = advance_date(row.starts_on, row.recurrence, step)
            if occurrence < row.next_run_on:
                step += 1
                continue
            if occurrence > today:
                break
            if row.ends_on is not None and occurrence > row.ends_on:
                break
            idempotency_key = f"recurring:{row.id}:{occurrence.isoformat()}"
            signature = _recurring_signature(row, occurrence)
            outcome = await _materialize_occurrence(
                session,
                recurring=row,
                occurrence=occurrence,
                idempotency_key=idempotency_key,
                signature=signature,
            )
            if outcome:
                created += 1
            else:
                replayed += 1
            step += 1
        next_run = advance_date(row.starts_on, row.recurrence, step)
        row.next_run_on = next_run
        if row.ends_on is not None and next_run > row.ends_on:
            row.is_active = False
    return MaterializeResult(created=created, replayed=replayed, paused=paused)


def _occurrence_datetime(occurrence: date) -> datetime:
    return datetime(
        occurrence.year, occurrence.month, occurrence.day, *_OCCURRENCE_TIME, tzinfo=UTC
    )


def _recurring_signature(row: RecurringTransaction, occurrence: date) -> str:
    payload = json.dumps(
        {
            "operation_type": row.template_operation_type,
            "amount_cents": row.template_amount_cents,
            "occurred_at": _occurrence_datetime(occurrence).isoformat(),
            "description": row.template_description,
            "external_id": None,
            "fingerprint": f"recurring:{row.id}",
            "reverses_transaction_id": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _materialize_occurrence(
    session: AsyncSession,
    recurring: RecurringTransaction,
    occurrence: date,
    idempotency_key: str,
    signature: str,
) -> bool:
    existing = await session.execute(
        select(Transaction).where(
            Transaction.account_id == recurring.account_id,
            Transaction.idempotency_key == idempotency_key,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        if found.payload_signature != signature:
            raise IdempotencyConflictError("idempotency key reused with different payload")
        return False

    locked = (
        await session.execute(
            select(Account.current_balance_cents, Account.current_balance_version)
            .where(Account.id == recurring.account_id)
            .with_for_update()
        )
    ).one()
    delta = (
        recurring.template_amount_cents
        if recurring.template_operation_type == "deposit"
        else -recurring.template_amount_cents
    )
    balance_after = int(locked.current_balance_cents) + delta
    version_after = int(locked.current_balance_version) + 1

    insert_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=recurring.user_id,
            account_id=recurring.account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind="credit" if recurring.template_operation_type == "deposit" else "debit",
            operation_type=recurring.template_operation_type,
            status="posted",
            amount_cents=recurring.template_amount_cents,
            occurred_at=_occurrence_datetime(occurrence),
            description=recurring.template_description,
            external_id=None,
            fingerprint=f"recurring:{recurring.id}",
            reversal_of_id=None,
            result_balance_after_cents=balance_after,
            result_balance_version=version_after,
        )
        .on_conflict_do_nothing(
            index_elements=[Transaction.account_id, Transaction.idempotency_key]
        )
        .returning(Transaction.id)
    )
    inserted = (await session.execute(insert_stmt)).first()
    if inserted is None:
        winner = await session.execute(
            select(Transaction).where(
                Transaction.account_id == recurring.account_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
        winner_row = winner.scalar_one_or_none()
        if winner_row is None or winner_row.payload_signature != signature:
            raise IdempotencyConflictError("idempotency key reused with different payload")
        return False

    await session.execute(
        update(Account)
        .where(Account.id == recurring.account_id)
        .values(
            current_balance_cents=balance_after,
            current_balance_version=version_after,
            updated_at=func.now(),
        )
    )
    return True
