import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, Transaction, User
from app.services.ledger import IdempotencyConflictError
from app.services.scheduled import ScheduledResult, create_scheduled


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


async def _seed(db_session: AsyncSession) -> Account:
    user = User(
        email=f"corrida-{uuid.uuid4().hex[:10]}@example.com",
        name="Corrida",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Corrida A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return account


def _common(account: Account, key: str, occurred_at: datetime, amount: int) -> _CommonKwargs:
    return _CommonKwargs(
        account_id=account.id,
        user_id=account.user_id,
        idempotency_key=key,
        operation_type="withdrawal",
        amount_cents=amount,
        occurred_at=occurred_at,
        description="corrida",
        external_id=None,
        fingerprint=None,
    )


@pytest.mark.asyncio
async def test_concurrent_same_key_same_payload_converge(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _seed(db_session)
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    key = f"corrida-{uuid.uuid4().hex[:10]}"
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async def attempt(amount: int = 15000) -> ScheduledResult:
        async with factory() as session:
            await set_bypass_scope(session)
            try:
                result = await create_scheduled(
                    session, **_common(account, key, occurred_at, amount)
                )
                await session.commit()
                return result
            except IntegrityError:
                await session.rollback()
                raise

    first, second = await asyncio.gather(attempt(), attempt())

    assert first is not None and second is not None
    assert first.transaction_id == second.transaction_id
    assert {first.created, second.created} == {True, False}

    async with factory() as session:
        await set_bypass_scope(session)
        total = (
            await session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.account_id == account.id,
                    Transaction.idempotency_key == key,
                )
            )
        ).scalar_one()
        assert total == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_different_payload_conflicts(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _seed(db_session)
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    key = f"corrida-x-{uuid.uuid4().hex[:10]}"
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async def attempt(amount: int) -> tuple[int, ScheduledResult | None]:
        async with factory() as session:
            await set_bypass_scope(session)
            try:
                result = await create_scheduled(
                    session, **_common(account, key, occurred_at, amount)
                )
                await session.commit()
                return amount, result
            except IdempotencyConflictError:
                await session.rollback()
                return amount, None

    (amount_a, first), (amount_b, second) = await asyncio.gather(attempt(15000), attempt(25000))

    successes = [
        (amt, obj) for amt, obj in ((amount_a, first), (amount_b, second)) if obj is not None
    ]
    assert len(successes) == 1, "exactly one concurrent winner is allowed"
    winner_amount, _winner = successes[0]

    async with factory() as session:
        await set_bypass_scope(session)
        rows = (
            (
                await session.execute(
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
        assert rows[0].amount_cents == winner_amount
