import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction


@dataclass(frozen=True, slots=True)
class LedgerResult:
    transaction_id: UUID
    account_id: UUID
    kind: str
    amount_cents: int
    balance_after_cents: int
    balance_version: int
    created: bool
    reversal_of_id: UUID | None = None


class LedgerError(Exception):
    pass


class IdempotencyConflictError(LedgerError):
    pass


class DomainConflictError(LedgerError):
    pass


class StaleVersionError(LedgerError):
    pass


@dataclass(frozen=True, slots=True)
class TransferResult:
    transfer_group_id: UUID
    out_transaction_id: UUID
    in_transaction_id: UUID
    amount_cents: int


async def _transfer_replay_result(
    session: AsyncSession,
    out_leg: Transaction,
    amount_cents: int,
) -> TransferResult:
    group_id = out_leg.transfer_group_id
    if group_id is None:
        raise LedgerError("stored transfer leg missing group id")
    in_leg = await session.execute(
        select(Transaction).where(
            Transaction.transfer_group_id == group_id,
            Transaction.operation_type == "transfer_in",
        )
    )
    in_leg_row = in_leg.scalar_one()
    return TransferResult(
        transfer_group_id=group_id,
        out_transaction_id=out_leg.id,
        in_transaction_id=in_leg_row.id,
        amount_cents=amount_cents,
    )


async def apply_transfer(
    session: AsyncSession,
    from_account_id: UUID,
    to_account_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    amount_cents: int,
    occurred_at: datetime,
) -> TransferResult:
    if amount_cents <= 0:
        raise LedgerError("amount must be positive")
    if from_account_id == to_account_id:
        raise LedgerError("transfer requires distinct accounts")

    from_account = await session.get(Account, from_account_id)
    to_account = await session.get(Account, to_account_id)
    if from_account is None or from_account.user_id != user_id:
        raise LedgerError("source account not found for owner")
    if to_account is None or to_account.user_id != user_id:
        raise LedgerError("destination account not found for owner")

    signature = _payload_signature(
        "transfer",
        amount_cents,
        occurred_at,
        None,
        None,
        f"{from_account_id}:{to_account_id}",
        None,
    )

    existing_out = await session.execute(
        select(Transaction).where(
            Transaction.account_id == from_account_id,
            Transaction.idempotency_key == idempotency_key,
        )
    )
    replay_leg = existing_out.scalar_one_or_none()
    if replay_leg is not None:
        if replay_leg.payload_signature != signature:
            raise IdempotencyConflictError("idempotency key reused with different payload")
        return await _transfer_replay_result(session, replay_leg, amount_cents)

    group_id = uuid.uuid4()
    first_lock_id, second_lock_id = sorted((from_account_id, to_account_id))
    locked_rows = (
        await session.execute(
            select(Account.id, Account.current_balance_cents, Account.current_balance_version)
            .where(Account.id.in_([first_lock_id, second_lock_id]))
            .with_for_update()
        )
    ).all()
    locked_by_id = {row.id: row for row in locked_rows}
    source_locked = locked_by_id[from_account_id]
    destination_locked = locked_by_id[to_account_id]
    out_balance_after = source_locked.current_balance_cents - amount_cents
    out_version_after = source_locked.current_balance_version + 1
    in_balance_after = destination_locked.current_balance_cents + amount_cents
    in_version_after = destination_locked.current_balance_version + 1

    out_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=from_account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind="debit",
            operation_type="transfer_out",
            status="posted",
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            transfer_group_id=group_id,
            result_balance_after_cents=out_balance_after,
            result_balance_version=out_version_after,
        )
        .on_conflict_do_nothing(
            index_elements=[Transaction.account_id, Transaction.idempotency_key]
        )
        .returning(Transaction.id)
    )
    out_row = (await session.execute(out_stmt)).first()
    if out_row is None:
        winner = await session.execute(
            select(Transaction).where(
                Transaction.account_id == from_account_id,
                Transaction.idempotency_key == idempotency_key,
            )
        )
        winner_row = winner.scalar_one_or_none()
        if winner_row is None or winner_row.payload_signature != signature:
            raise IdempotencyConflictError("idempotency key reused with different payload")
        return await _transfer_replay_result(session, winner_row, amount_cents)
    in_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=to_account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind="credit",
            operation_type="transfer_in",
            status="posted",
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            transfer_group_id=group_id,
            result_balance_after_cents=in_balance_after,
            result_balance_version=in_version_after,
        )
        .on_conflict_do_nothing(
            index_elements=[Transaction.account_id, Transaction.idempotency_key]
        )
        .returning(Transaction.id)
    )
    in_row = (await session.execute(in_stmt)).first()
    if in_row is None:
        raise LedgerError("unable to persist transfer destination leg")

    await session.execute(
        update(Account)
        .where(Account.id == from_account_id)
        .values(
            current_balance_cents=out_balance_after,
            current_balance_version=out_version_after,
            updated_at=func.now(),
        )
    )
    await session.execute(
        update(Account)
        .where(Account.id == to_account_id)
        .values(
            current_balance_cents=in_balance_after,
            current_balance_version=in_version_after,
            updated_at=func.now(),
        )
    )

    return TransferResult(
        transfer_group_id=group_id,
        out_transaction_id=out_row.id,
        in_transaction_id=in_row.id,
        amount_cents=amount_cents,
    )


async def apply_reversal(
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
    transaction_id: UUID,
    idempotency_key: str,
    expected_version: int | None,
) -> LedgerResult:
    original = await session.get(Transaction, transaction_id)
    if original is None or original.user_id != user_id or original.account_id != account_id:
        raise LedgerError("original transaction not found for reversal")
    if original.operation_type == "reversal" or original.reversal_of_id is not None:
        raise DomainConflictError("transaction already reversed")

    signature = _payload_signature(
        "reversal",
        original.amount_cents,
        original.occurred_at,
        None,
        None,
        None,
        transaction_id,
    )
    replay = await _existing_result(session, account_id, idempotency_key, signature)
    if replay is not None:
        return replay

    already = await session.execute(
        select(Transaction.id).where(Transaction.reversal_of_id == transaction_id)
    )
    if already.scalar_one_or_none() is not None:
        raise DomainConflictError("transaction already reversed")

    locked_stmt = (
        select(Account.current_balance_cents, Account.current_balance_version)
        .where(Account.id == account_id)
        .with_for_update()
    )
    if expected_version is not None:
        locked_stmt = locked_stmt.where(Account.current_balance_version == expected_version)
    locked = (await session.execute(locked_stmt)).one_or_none()
    if locked is None:
        if expected_version is None:
            raise LedgerError("account not found for owner")
        raise StaleVersionError("stale balance version, reload and retry")

    recheck = await session.execute(
        select(Transaction.id).where(Transaction.reversal_of_id == transaction_id)
    )
    if recheck.scalar_one_or_none() is not None:
        raise DomainConflictError("transaction already reversed")

    kind = "debit" if original.kind == "credit" else "credit"
    delta = original.amount_cents if kind == "credit" else -original.amount_cents
    balance_after = locked.current_balance_cents + delta
    version_after = locked.current_balance_version + 1

    insert_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind=kind,
            operation_type="reversal",
            status="posted",
            amount_cents=original.amount_cents,
            occurred_at=original.occurred_at,
            reversal_of_id=transaction_id,
            result_balance_after_cents=balance_after,
            result_balance_version=version_after,
        )
        .on_conflict_do_nothing()
        .returning(Transaction.id)
    )
    inserted = (await session.execute(insert_stmt)).first()
    if inserted is None:
        replay_after_race = await _existing_result(session, account_id, idempotency_key, signature)
        if replay_after_race is not None:
            return replay_after_race
        raise DomainConflictError("transaction already reversed")

    await session.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(
            current_balance_cents=balance_after,
            current_balance_version=version_after,
            updated_at=func.now(),
        )
    )

    return LedgerResult(
        transaction_id=inserted.id,
        account_id=account_id,
        kind=kind,
        amount_cents=original.amount_cents,
        balance_after_cents=balance_after,
        balance_version=version_after,
        created=True,
        reversal_of_id=transaction_id,
    )


_ALLOWED_OPERATIONS = ("deposit", "withdrawal", "reversal")


def _payload_signature(
    operation_type: str,
    amount_cents: int,
    occurred_at: datetime,
    description: str | None,
    external_id: str | None,
    fingerprint: str | None,
    reverses_transaction_id: UUID | None,
) -> str:
    payload = json.dumps(
        {
            "operation_type": operation_type,
            "amount_cents": amount_cents,
            "occurred_at": occurred_at.isoformat(),
            "description": description,
            "external_id": external_id,
            "fingerprint": fingerprint,
            "reverses_transaction_id": (
                str(reverses_transaction_id) if reverses_transaction_id else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _existing_result(
    session: AsyncSession, account_id: UUID, idempotency_key: str, signature: str
) -> LedgerResult | None:
    row = await session.execute(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.idempotency_key == idempotency_key,
        )
    )
    existing = row.scalar_one_or_none()
    if existing is None:
        return None
    if existing.payload_signature != signature:
        raise IdempotencyConflictError("idempotency key reused with different payload")
    return LedgerResult(
        transaction_id=existing.id,
        account_id=existing.account_id,
        kind=existing.kind,
        amount_cents=existing.amount_cents,
        balance_after_cents=existing.result_balance_after_cents,
        balance_version=existing.result_balance_version,
        created=False,
        reversal_of_id=existing.reversal_of_id,
    )


async def apply_ledger_movement(
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
    reverses_transaction_id: UUID | None = None,
) -> LedgerResult:
    if operation_type not in _ALLOWED_OPERATIONS:
        raise LedgerError("unsupported operation type")
    if amount_cents <= 0:
        raise LedgerError("amount must be positive")

    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise LedgerError("account not found for owner")

    signature = _payload_signature(
        operation_type,
        amount_cents,
        occurred_at,
        description,
        external_id,
        fingerprint,
        reverses_transaction_id,
    )
    replay = await _existing_result(session, account_id, idempotency_key, signature)
    if replay is not None:
        return replay

    kind = "credit"
    if operation_type == "withdrawal":
        kind = "debit"
    elif operation_type == "reversal":
        if reverses_transaction_id is None:
            raise LedgerError("reversal requires the original transaction")
        original = await session.get(Transaction, reverses_transaction_id)
        if original is None or original.user_id != user_id or original.account_id != account_id:
            raise LedgerError("original transaction not found for reversal")
        if original.amount_cents != amount_cents:
            raise LedgerError("reversal amount must match the original")
        kind = "debit" if original.kind == "credit" else "credit"

    locked = (
        await session.execute(
            select(Account.current_balance_cents, Account.current_balance_version)
            .where(Account.id == account_id)
            .with_for_update()
        )
    ).one()
    delta = amount_cents if kind == "credit" else -amount_cents
    balance_after = locked.current_balance_cents + delta
    version_after = locked.current_balance_version + 1

    insert_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
            payload_signature=signature,
            kind=kind,
            operation_type=operation_type,
            status="posted",
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            description=description,
            external_id=external_id,
            fingerprint=fingerprint,
            reversal_of_id=reverses_transaction_id,
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
        replay_after_race = await _existing_result(session, account_id, idempotency_key, signature)
        if replay_after_race is None:
            raise LedgerError("unable to persist ledger movement")
        return replay_after_race

    await session.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(
            current_balance_cents=balance_after,
            current_balance_version=version_after,
            updated_at=func.now(),
        )
    )

    return LedgerResult(
        transaction_id=inserted.id,
        account_id=account_id,
        kind=kind,
        amount_cents=amount_cents,
        balance_after_cents=balance_after,
        balance_version=version_after,
        created=True,
        reversal_of_id=reverses_transaction_id,
    )
