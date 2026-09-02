import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup_user_with_account(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, name, is_active)"
            " VALUES (:id, :email, 'x', 'U', true)"
        ),
        {"id": user_id, "email": f"tx-{user_id}@example.com"},
    )
    account_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO accounts (id, user_id, name, kind, currency,"
            " initial_balance_cents, current_balance_cents, current_balance_version)"
            " VALUES (:id, :user_id, 'Conta Tx', 'checking', 'BRL', 100000, 100000, 0)"
        ),
        {"id": account_id, "user_id": user_id},
    )
    await db_session.commit()
    return user_id, account_id


async def test_transactions_move_ledger_and_support_reversal(
    db_session: AsyncSession,
) -> None:
    from app.services.ledger import IdempotencyConflictError, apply_ledger_movement

    user_id, account_id = await _setup_user_with_account(db_session)

    occurred = datetime.now(UTC)
    first = await apply_ledger_movement(
        db_session,
        account_id=account_id,
        user_id=user_id,
        idempotency_key="op-dep",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred,
    )
    assert first.balance_after_cents == 150000
    assert first.balance_version == 1

    withdrawal = await apply_ledger_movement(
        db_session,
        account_id=account_id,
        user_id=user_id,
        idempotency_key="op-wd",
        operation_type="withdrawal",
        amount_cents=32000,
        occurred_at=datetime.now(UTC),
    )
    assert withdrawal.balance_after_cents == 118000

    replay = await apply_ledger_movement(
        db_session,
        account_id=account_id,
        user_id=user_id,
        idempotency_key="op-dep",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred,
    )
    assert replay.transaction_id == first.transaction_id
    assert replay.created is False

    with pytest.raises(IdempotencyConflictError):
        await apply_ledger_movement(
            db_session,
            account_id=account_id,
            user_id=user_id,
            idempotency_key="op-dep",
            operation_type="deposit",
            amount_cents=99999,
            occurred_at=occurred,
        )

    reversal = await apply_ledger_movement(
        db_session,
        account_id=account_id,
        user_id=user_id,
        idempotency_key="op-rev",
        operation_type="reversal",
        amount_cents=32000,
        occurred_at=datetime.now(UTC),
        reverses_transaction_id=withdrawal.transaction_id,
    )
    assert reversal.kind == "credit"
    assert reversal.balance_after_cents == 150000
    assert reversal.balance_version == 3

    total = await db_session.execute(
        text(
            "SELECT COALESCE(SUM(CASE WHEN kind = 'credit' THEN amount_cents"
            " ELSE -amount_cents END), 0) FROM transactions WHERE account_id = :a"
        ),
        {"a": account_id},
    )
    assert total.scalar_one() == 50000


async def test_reversal_rejects_wrong_amount_and_cross_account(
    db_session: AsyncSession,
) -> None:
    from app.services.ledger import LedgerError, apply_ledger_movement

    user_id, account_id = await _setup_user_with_account(db_session)
    deposit = await apply_ledger_movement(
        db_session,
        account_id=account_id,
        user_id=user_id,
        idempotency_key="d1",
        operation_type="deposit",
        amount_cents=1000,
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(LedgerError):
        await apply_ledger_movement(
            db_session,
            account_id=account_id,
            user_id=user_id,
            idempotency_key="r1",
            operation_type="reversal",
            amount_cents=999,
            occurred_at=datetime.now(UTC),
            reverses_transaction_id=deposit.transaction_id,
        )

    other_account = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO accounts (id, user_id, name, kind, currency,"
            " initial_balance_cents, current_balance_cents, current_balance_version)"
            " VALUES (:id, :user_id, 'Outra', 'savings', 'BRL', 0, 0, 0)"
        ),
        {"id": other_account, "user_id": user_id},
    )
    await db_session.commit()
    with pytest.raises(LedgerError):
        await apply_ledger_movement(
            db_session,
            account_id=other_account,
            user_id=user_id,
            idempotency_key="r2",
            operation_type="reversal",
            amount_cents=1000,
            occurred_at=datetime.now(UTC),
            reverses_transaction_id=deposit.transaction_id,
        )
