import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, User
from app.services.ledger import (
    DomainConflictError,
    IdempotencyConflictError,
    StaleVersionError,
    apply_ledger_movement,
    apply_reversal,
)


def occurred(hour: int = 10) -> datetime:
    return datetime(2026, 9, 1, hour, 0, tzinfo=UTC)


async def _make_user_account(
    db_session: AsyncSession, label: str, balance: int
) -> tuple[User, Account]:
    user = User(
        email=f"revrace-{label}-{uuid.uuid4().hex[:10]}@example.com",
        name=label,
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name=label,
        kind="checking",
        currency="BRL",
        initial_balance_cents=balance,
        current_balance_cents=balance,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return user, account


async def _deposit(
    engine: AsyncEngine, user: User, account: Account, key: str, amount: int
) -> uuid.UUID:
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        await set_bypass_scope(session)
        result = await apply_ledger_movement(
            session,
            account_id=account.id,
            user_id=user.id,
            idempotency_key=key,
            operation_type="deposit",
            amount_cents=amount,
            occurred_at=occurred(),
        )
        await session.commit()
        return result.transaction_id


@pytest.mark.asyncio
async def test_two_concurrent_reversals_apply_exactly_once(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, account = await _make_user_account(db_session, "Race", 50000)
    deposit_id = await _deposit(migrated_engine, user, account, "race-dep", 20000)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    barrier = asyncio.Barrier(2)

    async def attempt(key: str) -> tuple[str, uuid.UUID | None]:
        async with factory() as session:
            await set_bypass_scope(session)
            try:
                await barrier.wait()
                result = await apply_reversal(
                    session,
                    account_id=account.id,
                    user_id=user.id,
                    transaction_id=deposit_id,
                    idempotency_key=key,
                    expected_version=None,
                )
                await session.commit()
                return "applied", result.transaction_id
            except DomainConflictError:
                await session.rollback()
                return "conflict", None

    results = await asyncio.gather(attempt("race-k1"), attempt("race-k2"))
    statuses = [status for status, _ in results]
    assert statuses.count("applied") == 1
    assert statuses.count("conflict") == 1

    async with factory() as session:
        await set_bypass_scope(session)
        reversals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM transactions"
                    " WHERE operation_type = 'reversal' AND reversal_of_id = :tx"
                ),
                {"tx": deposit_id},
            )
        ).scalar_one()
        assert reversals == 1
        balance, version = (
            await session.execute(
                text(
                    "SELECT current_balance_cents, current_balance_version"
                    " FROM accounts WHERE id = :a"
                ),
                {"a": account.id},
            )
        ).one()
        assert balance == 50000
        assert version == 2


@pytest.mark.asyncio
async def test_reversal_replays_same_key_and_rejects_second_reversal(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, account = await _make_user_account(db_session, "Replay", 30000)
    deposit_id = await _deposit(migrated_engine, user, account, "replay-dep", 12000)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        await set_bypass_scope(session)
        first = await apply_reversal(
            session,
            account_id=account.id,
            user_id=user.id,
            transaction_id=deposit_id,
            idempotency_key="replay-k1",
            expected_version=None,
        )
        await session.commit()
        async with factory() as session:
            await set_bypass_scope(session)
            replay = await apply_reversal(
                session,
                account_id=account.id,
                user_id=user.id,
                transaction_id=deposit_id,
                idempotency_key="replay-k1",
                expected_version=None,
            )
            assert replay.transaction_id == first.transaction_id
            assert replay.balance_after_cents == first.balance_after_cents
            assert replay.balance_version == first.balance_version
        with pytest.raises(DomainConflictError):
            async with factory() as session:
                await set_bypass_scope(session)
                await apply_reversal(
                    session,
                    account_id=account.id,
                    user_id=user.id,
                    transaction_id=deposit_id,
                    idempotency_key="replay-k2",
                    expected_version=None,
                )
        async with factory() as session:
            await set_bypass_scope(session)
            reversals = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM transactions"
                        " WHERE operation_type = 'reversal' AND reversal_of_id = :tx"
                    ),
                    {"tx": deposit_id},
                )
            ).scalar_one()
            assert reversals == 1


@pytest.mark.asyncio
async def test_reversal_expected_version_is_atomic_compare_and_swap(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, account = await _make_user_account(db_session, "Cas", 10000)
    deposit_id = await _deposit(migrated_engine, user, account, "cas-dep", 4000)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        await set_bypass_scope(session)
        with pytest.raises(StaleVersionError):
            await apply_reversal(
                session,
                account_id=account.id,
                user_id=user.id,
                transaction_id=deposit_id,
                idempotency_key="cas-k1",
                expected_version=0,
            )
        await session.rollback()
        balance_version = (
            await session.execute(
                text("SELECT current_balance_version FROM accounts WHERE id = :a"),
                {"a": account.id},
            )
        ).scalar_one()
        assert balance_version == 1

    async with factory() as session:
        await set_bypass_scope(session)
        result = await apply_reversal(
            session,
            account_id=account.id,
            user_id=user.id,
            transaction_id=deposit_id,
            idempotency_key="cas-k2",
            expected_version=1,
        )
        await session.commit()
        assert result.balance_version == 2


@pytest.mark.asyncio
async def test_reversal_key_conflict_with_different_target_payload(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user, account = await _make_user_account(db_session, "Sig", 80000)
    first_id = await _deposit(migrated_engine, user, account, "sig-dep-1", 5000)
    second_id = await _deposit(migrated_engine, user, account, "sig-dep-2", 7000)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async with factory() as session:
        await set_bypass_scope(session)
        await apply_reversal(
            session,
            account_id=account.id,
            user_id=user.id,
            transaction_id=first_id,
            idempotency_key="sig-k1",
            expected_version=None,
        )
        await session.commit()

    with pytest.raises(IdempotencyConflictError):
        async with factory() as session:
            await set_bypass_scope(session)
            await apply_reversal(
                session,
                account_id=account.id,
                user_id=user.id,
                transaction_id=second_id,
                idempotency_key="sig-k1",
                expected_version=None,
            )
