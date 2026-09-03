from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction
from app.services.ledger import IdempotencyConflictError, payload_signature

_ALLOWED_SCHEDULED_OPERATIONS = ("deposit", "withdrawal")


@dataclass(frozen=True, slots=True)
class ScheduledResult:
    transaction_id: UUID
    account_id: UUID
    status: str
    created: bool


class ScheduledError(Exception):
    pass


async def create_scheduled(
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    operation_type: str,
    amount_cents: int,
    occurred_at: datetime,
    description: str | None = None,
    external_id: str | None = None,
    fingerprint: str | None = None,
) -> ScheduledResult:
    if amount_cents <= 0:
        raise ScheduledError("amount must be positive")
    if operation_type not in _ALLOWED_SCHEDULED_OPERATIONS:
        raise ScheduledError("unsupported scheduled operation type")
    if occurred_at <= datetime.now(UTC):
        raise ScheduledError("scheduled transactions require a future occurred_at")

    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise ScheduledError("account not found for owner")

    signature = payload_signature(
        operation_type,
        amount_cents,
        occurred_at,
        description,
        external_id,
        fingerprint,
        None,
    )

    insert_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind="credit" if operation_type == "deposit" else "debit",
            operation_type=operation_type,
            status="pending",
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            description=description,
            external_id=external_id,
            fingerprint=fingerprint,
            result_balance_after_cents=0,
            result_balance_version=0,
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
                Transaction.account_id == account_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
        winner_row = winner.scalar_one_or_none()
        if winner_row is None or winner_row.payload_signature != signature:
            raise IdempotencyConflictError("idempotency key reused with different payload")
        return ScheduledResult(
            transaction_id=winner_row.id,
            account_id=account_id,
            status=winner_row.status,
            created=False,
        )

    return ScheduledResult(
        transaction_id=inserted.id,
        account_id=account_id,
        status="pending",
        created=True,
    )


async def promote_due(
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
    today: datetime,
) -> int:
    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise ScheduledError("account not found for owner")

    await session.execute(select(Account.id).where(Account.id == account_id).with_for_update())

    due_rows = await session.execute(
        select(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.user_id == user_id,
            Transaction.status == "pending",
            Transaction.occurred_at <= today,
        )
        .order_by(Transaction.occurred_at, Transaction.created_at, Transaction.id)
    )
    promoted = 0
    for row in due_rows.scalars():
        fresh_status = (
            await session.execute(
                select(Transaction.status).where(Transaction.id == row.id).with_for_update()
            )
        ).scalar_one()
        if fresh_status != "pending":
            continue
        locked = (
            await session.execute(
                select(Account.current_balance_cents, Account.current_balance_version)
                .where(Account.id == account_id)
                .with_for_update()
            )
        ).one()
        delta = row.amount_cents if row.kind == "credit" else -row.amount_cents
        balance_after = int(locked.current_balance_cents) + delta
        version_after = int(locked.current_balance_version) + 1
        await session.execute(
            update(Transaction)
            .where(Transaction.id == row.id)
            .values(
                status="posted",
                result_balance_after_cents=balance_after,
                result_balance_version=version_after,
            )
        )
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(
                current_balance_cents=balance_after,
                current_balance_version=version_after,
                updated_at=func.now(),
            )
        )
        promoted += 1
    return promoted
