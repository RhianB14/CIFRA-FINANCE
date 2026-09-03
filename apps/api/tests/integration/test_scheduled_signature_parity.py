import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction
from app.services.ledger import (
    IdempotencyConflictError,
    apply_ledger_movement,
)
from app.services.scheduled import create_scheduled


class _CommonKwargs(TypedDict):
    account_id: UUID
    user_id: UUID
    idempotency_key: str
    operation_type: str
    amount_cents: int
    occurred_at: datetime
    description: str | None
    external_id: str | None
    fingerprint: str | None


@pytest.mark.asyncio
async def test_replay_crossing_due_date_keeps_same_signature(
    db_session: AsyncSession,
) -> None:
    from app.core.db import set_bypass_scope
    from app.models import Account, User

    user = User(
        email=f"cruz-{uuid.uuid4().hex[:10]}@example.com",
        name="Cruz",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Cruz A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    await set_bypass_scope(db_session)

    key = f"cruz-{uuid.uuid4().hex[:10]}"
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    common = _CommonKwargs(
        account_id=account.id,
        user_id=user.id,
        idempotency_key=key,
        operation_type="withdrawal",
        amount_cents=12000,
        occurred_at=occurred_at,
        description="f3 cross",
        external_id=None,
        fingerprint=None,
    )

    created = await create_scheduled(db_session, **common)
    await db_session.commit()
    assert created.created is True

    replayed = await apply_ledger_movement(db_session, **common, reverses_transaction_id=None)
    await db_session.commit()
    assert replayed.created is False
    assert replayed.transaction_id == created.transaction_id

    rows = (
        (
            await db_session.execute(
                select(Transaction).where(
                    Transaction.account_id == account.id,
                    Transaction.idempotency_key == key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1

    conflicting: _CommonKwargs = {**common, "amount_cents": 1}
    with pytest.raises(IdempotencyConflictError):
        await apply_ledger_movement(
            db_session,
            **conflicting,
            reverses_transaction_id=None,
        )
