import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, Transaction, User
from app.services.ledger import (
    IdempotencyConflictError,
    apply_transfer,
)


def occurred(hour: int = 10) -> datetime:
    return datetime(2026, 9, 1, hour, 0, tzinfo=UTC)


async def _make_user_accounts(
    db_session: AsyncSession, label: str
) -> tuple[User, Account, Account]:
    user = User(
        email=f"transfer-race-{label}-{uuid.uuid4().hex[:10]}@example.com",
        name=label,
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    src = Account(
        user_id=user.id,
        name=f"{label} src",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    dst = Account(
        user_id=user.id,
        name=f"{label} dst",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    db_session.add_all([src, dst])
    await db_session.commit()
    return user, src, dst


@pytest.mark.asyncio
async def test_concurrent_same_payload_transfer_replays_idempotently(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, src, dst = await _make_user_accounts(db_session, "Same")
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async def attempt() -> tuple[uuid.UUID, int]:
        async with factory() as session:
            await set_bypass_scope(session)
            result = await apply_transfer(
                session,
                from_account_id=src.id,
                to_account_id=dst.id,
                user_id=user.id,
                idempotency_key="xfer-race-1",
                amount_cents=30000,
                occurred_at=occurred(),
            )
            await session.commit()
            return result.out_transaction_id, result.amount_cents

    results = await asyncio.gather(attempt(), attempt())
    (out_a, amount_a), (out_b, amount_b) = results
    assert out_a == out_b
    assert amount_a == amount_b == 30000

    async with factory() as session:
        await set_bypass_scope(session)
        legs = (
            await session.execute(
                text("SELECT COUNT(*) FROM transactions WHERE transfer_group_id IS NOT NULL")
            )
        ).scalar_one()
        assert legs == 2
        rows = (
            await session.execute(
                text(
                    "SELECT id, current_balance_cents, current_balance_version FROM accounts"
                    " WHERE id IN (:s, :d)"
                ),
                {"s": src.id, "d": dst.id},
            )
        ).all()
        by_id = {row[0]: (row[1], row[2]) for row in rows}
        assert by_id[src.id] == (70000, 1)
        assert by_id[dst.id] == (30000, 1)


@pytest.mark.asyncio
async def test_concurrent_conflicting_payload_transfer_yields_single_conflict(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, src, dst = await _make_user_accounts(db_session, "Diff")
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    barrier = asyncio.Barrier(2)

    async def attempt(amount: int) -> tuple[str, int | None]:
        async with factory() as session:
            await set_bypass_scope(session)
            try:
                await barrier.wait()
                result = await apply_transfer(
                    session,
                    from_account_id=src.id,
                    to_account_id=dst.id,
                    user_id=user.id,
                    idempotency_key="xfer-race-2",
                    amount_cents=amount,
                    occurred_at=occurred(),
                )
                await session.commit()
                return "created", result.amount_cents
            except IdempotencyConflictError:
                await session.rollback()
                return "conflict", None

    results = await asyncio.gather(attempt(10000), attempt(25000))
    statuses = [status for status, _ in results]
    assert statuses.count("created") == 1
    assert statuses.count("conflict") == 1

    async with factory() as session:
        await set_bypass_scope(session)
        legs = (
            await session.execute(
                text("SELECT COUNT(*) FROM transactions WHERE transfer_group_id IS NOT NULL")
            )
        ).scalar_one()
        assert legs == 2
        src_balance = (
            await session.execute(
                text("SELECT current_balance_cents FROM accounts WHERE id = :a"),
                {"a": src.id},
            )
        ).scalar_one()
        assert src_balance in (90000, 75000)


@pytest.mark.asyncio
async def test_transfer_conflicting_payload_after_winner_commits_rejects(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, src, dst = await _make_user_accounts(db_session, "After")
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        await set_bypass_scope(session)
        first = await apply_transfer(
            session,
            from_account_id=src.id,
            to_account_id=dst.id,
            user_id=user.id,
            idempotency_key="xfer-after-1",
            amount_cents=12000,
            occurred_at=occurred(),
        )
        await session.commit()

    with pytest.raises(IdempotencyConflictError):
        async with factory() as session:
            await set_bypass_scope(session)
            await apply_transfer(
                session,
                from_account_id=src.id,
                to_account_id=dst.id,
                user_id=user.id,
                idempotency_key="xfer-after-1",
                amount_cents=13000,
                occurred_at=occurred(),
            )

    async with factory() as session:
        await set_bypass_scope(session)
        out = await session.get(Transaction, first.out_transaction_id)
        assert out is not None
        assert out.result_balance_after_cents == 88000
