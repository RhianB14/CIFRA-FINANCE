import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, User
from app.services.ledger import apply_ledger_movement


def occurred(hour: int) -> datetime:
    return datetime(2026, 9, 1, hour, tzinfo=UTC)


async def _seed(db_session: AsyncSession) -> tuple[User, Account]:
    user = User(
        email=f"replay-{uuid.uuid4().hex[:10]}@example.com",
        name="Replay",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Conta Replay",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return user, account


@pytest.mark.asyncio
async def test_replay_returns_original_balance_and_version(db_session: AsyncSession) -> None:
    user, account = await _seed(db_session)

    original = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="rp-1",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred(10),
    )
    assert original.created is True
    assert original.balance_after_cents == 150000
    assert original.balance_version == 1

    replay = await apply_ledger_movement(
        db_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key="rp-1",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred(10),
    )
    assert replay.created is False
    assert replay.balance_after_cents == original.balance_after_cents
    assert replay.balance_version == original.balance_version
