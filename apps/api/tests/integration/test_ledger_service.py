import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction, User
from app.services.ledger import IdempotencyConflictError, apply_ledger_movement


def occurred(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, tzinfo=UTC)


@pytest.mark.asyncio
async def test_movement_is_idempotent_and_balance_matches_invariant(
    db_session: AsyncSession,
) -> None:
    user = User(
        email=f"ledger-{uuid.uuid4().hex[:10]}@example.com",
        name="Ledger",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()

    account = Account(
        user_id=user.id,
        name="Conta A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()

    first = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="op-1",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred(10),
        description="entrada",
    )
    replay = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="op-1",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred(10),
        description="entrada",
    )
    assert first.transaction_id == replay.transaction_id
    with pytest.raises(IdempotencyConflictError):
        await apply_ledger_movement(
            db_session,
            account_id=account.id,
            user_id=user.id,
            idempotency_key="op-1",
            operation_type="withdrawal",
            amount_cents=50000,
            occurred_at=occurred(10),
            description="outro payload",
        )

    counted = await db_session.execute(
        text("SELECT COUNT(*) FROM transactions WHERE account_id = :account_id"),
        {"account_id": account.id},
    )
    assert counted.scalar_one() == 1

    movement = await db_session.execute(
        text(
            "SELECT COALESCE(SUM(CASE WHEN kind = 'credit'"
            " THEN amount_cents ELSE -amount_cents END), 0)"
            " FROM transactions WHERE account_id = :account_id"
        ),
        {"account_id": account.id},
    )
    ledger_balance = 100000 + movement.scalar_one()
    assert ledger_balance == 150000


@pytest.mark.asyncio
async def test_reversal_appends_and_never_updates_original(db_session: AsyncSession) -> None:
    user = User(
        email=f"rev-{uuid.uuid4().hex[:10]}@example.com",
        name="Rev",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()

    account = Account(
        user_id=user.id,
        name="Conta R",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()

    created = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="rev-1",
        operation_type="deposit",
        amount_cents=10000,
        occurred_at=occurred(11),
        description="original",
    )
    reversal = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="rev-1-reversal",
        operation_type="reversal",
        amount_cents=10000,
        occurred_at=occurred(11, 30),
        description="estorno",
        reverses_transaction_id=created.transaction_id,
    )

    assert reversal.reversal_of_id == created.transaction_id
    original = await db_session.get(Transaction, created.transaction_id)
    assert original is not None
    assert original.reversal_of_id is None
    assert original.kind == "credit"
    assert reversal.kind == "debit"
