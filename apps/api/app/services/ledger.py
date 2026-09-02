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


@dataclass(frozen=True, slots=True)
class TransferResult:
    transfer_group_id: UUID
    out_transaction_id: UUID
    in_transaction_id: UUID
    amount_cents: int


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
        group_id = replay_leg.transfer_group_id
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
            out_transaction_id=replay_leg.id,
            in_transaction_id=in_leg_row.id,
            amount_cents=amount_cents,
        )

    group_id = uuid.uuid4()
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
        )
        .on_conflict_do_nothing(
            index_elements=[Transaction.account_id, Transaction.idempotency_key]
        )
        .returning(Transaction.id)
    )
    out_row = (await session.execute(out_stmt)).first()
    if out_row is None:
        raise IdempotencyConflictError("idempotency key reused with different payload")
    in_stmt = (
        pg_insert(Transaction)
        .values(
            user_id=user_id,
            account_id=to_account_id,
            idempotency_key=f"{idempotency_key}:in",
            payload_signature=signature,
            kind="credit",
            operation_type="transfer_in",
            status="posted",
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            transfer_group_id=group_id,
        )
        .on_conflict_do_nothing(
            index_elements=[Transaction.account_id, Transaction.idempotency_key]
        )
        .returning(Transaction.id)
    )
    in_row = (await session.execute(in_stmt)).first()
    if in_row is None:
        raise LedgerError("unable to persist transfer destination leg")

    out_balance = await session.execute(
        update(Account)
        .where(Account.id == from_account_id)
        .values(
            current_balance_cents=Account.current_balance_cents - amount_cents,
            current_balance_version=Account.current_balance_version + 1,
            updated_at=func.now(),
        )
        .returning(Account.current_balance_version)
    )
    if out_balance.scalar_one_or_none() is None:
        raise LedgerError("source account balance update failed")
    in_balance = await session.execute(
        update(Account)
        .where(Account.id == to_account_id)
        .values(
            current_balance_cents=Account.current_balance_cents + amount_cents,
            current_balance_version=Account.current_balance_version + 1,
            updated_at=func.now(),
        )
        .returning(Account.current_balance_version)
    )
    if in_balance.scalar_one_or_none() is None:
        raise LedgerError("destination account balance update failed")

    return TransferResult(
        transfer_group_id=group_id,
        out_transaction_id=out_row.id,
        in_transaction_id=in_row.id,
        amount_cents=amount_cents,
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
        balance_after_cents=0,
        balance_version=0,
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

    delta = amount_cents if kind == "credit" else -amount_cents
    balance_row = await session.execute(
        update(Account)
        .where(Account.id == account_id)
        .values(
            current_balance_cents=Account.current_balance_cents + delta,
            current_balance_version=Account.current_balance_version + 1,
            updated_at=func.now(),
        )
        .returning(Account.current_balance_cents, Account.current_balance_version)
    )
    balance_after, version = balance_row.one()

    return LedgerResult(
        transaction_id=inserted.id,
        account_id=account_id,
        kind=kind,
        amount_cents=amount_cents,
        balance_after_cents=balance_after,
        balance_version=version,
        created=True,
        reversal_of_id=reverses_transaction_id,
    )
