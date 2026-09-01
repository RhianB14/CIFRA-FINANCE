import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.models import RefreshToken, User
from app.services.rotation import ReuseDetectedError, issue_refresh_token, rotate_refresh_token
from tests.conftest import alembic_config, async_url, recreate_database

ATOMIC_DB = "cifra_test_rotation_atomic"
RACE_ROUNDS = 3


@pytest_asyncio.fixture()
async def atomic_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(ATOMIC_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(ATOMIC_DB), "head")
    engine = create_async_engine(async_url(ATOMIC_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def redis_client() -> AsyncIterator[redis.Redis]:
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


def factory_for(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def make_user(factory: async_sessionmaker[AsyncSession]) -> User:
    async with factory() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            name="Ana",
            password_hash="x" * 20,
        )
        session.add(user)
        await session.commit()
        return user


async def token_rows(
    factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> list[RefreshToken]:
    async with factory() as session:
        result = await session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))
        return list(result.scalars().all())


async def test_successor_invisible_to_other_connection_before_rotation_commit(
    atomic_engine: AsyncEngine,
    redis_client: redis.Redis,
) -> None:
    factory = factory_for(atomic_engine)
    user = await make_user(factory)
    async with factory() as session:
        old_jwt, _ = await issue_refresh_token(session, user.id)
        await session.commit()

    issuer = factory_for(atomic_engine)()
    observer = factory_for(atomic_engine)()
    try:
        _, successor = await issue_refresh_token(issuer, user.id)
        visible = await token_rows(factory_for(atomic_engine), user.id)
        assert len(visible) == 1
        assert visible[0].id != successor.id
        await issuer.commit()
        visible_after = await token_rows(factory_for(atomic_engine), user.id)
        assert len(visible_after) == 2
    finally:
        await issuer.close()
        await observer.close()

    async with factory_for(atomic_engine)() as session:
        rotated = await rotate_refresh_token(session, old_jwt, redis_client)
        assert rotated[1].revoked_at is None


async def test_failed_rotation_commit_rolls_back_successor_and_revocation(
    atomic_engine: AsyncEngine,
    redis_client: redis.Redis,
) -> None:
    factory = factory_for(atomic_engine)
    user = await make_user(factory)
    async with factory() as session:
        old_jwt, old_row = await issue_refresh_token(session, user.id)
        await session.commit()

    commit_calls = 0

    class FailingSession(AsyncSession):
        async def commit(self) -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls >= 1:
                raise RuntimeError("simulated rotation commit failure")

    failing = FailingSession(bind=atomic_engine, expire_on_commit=False, autoflush=False)
    with pytest.raises(RuntimeError):
        await rotate_refresh_token(failing, old_jwt, redis_client)
    await failing.rollback()
    await failing.close()

    assert commit_calls == 1
    rows = await token_rows(factory, user.id)
    assert len(rows) == 1
    assert rows[0].id == old_row.id
    assert rows[0].revoked_at is None
    assert rows[0].replaced_by is None


async def test_concurrent_rotations_never_create_two_active_successors(
    atomic_engine: AsyncEngine,
    redis_client: redis.Redis,
) -> None:
    factory = factory_for(atomic_engine)
    user = await make_user(factory)
    for _ in range(RACE_ROUNDS):
        before = len(await token_rows(factory, user.id))
        async with factory() as session:
            jwt, _ = await issue_refresh_token(session, user.id)
            await session.commit()

        async def attempt(token: str) -> str:
            engine = create_async_engine(async_url(ATOMIC_DB))
            try:
                own_factory = factory_for(engine)
                async with own_factory() as session:
                    _, row = await rotate_refresh_token(session, token, redis_client)
                    return str(row.id)
            finally:
                await engine.dispose()

        results = await asyncio.gather(attempt(jwt), attempt(jwt), return_exceptions=True)
        successes = [r for r in results if isinstance(r, str)]
        reuses = [r for r in results if isinstance(r, ReuseDetectedError)]
        assert len(successes) == 1
        assert len(reuses) == 1
        rows = await token_rows(factory, user.id)
        assert len(rows) == before + 2
        assert all(token.revoked_at is not None for token in rows)


async def test_replaced_by_rejects_values_outside_refresh_tokens(
    atomic_engine: AsyncEngine,
    redis_client: redis.Redis,
) -> None:
    from sqlalchemy.exc import IntegrityError

    factory = factory_for(atomic_engine)
    user = await make_user(factory)
    async with factory() as session:
        old_jwt, old_row = await issue_refresh_token(session, user.id)
        await session.commit()
    async with factory() as session:
        _, new_row = await rotate_refresh_token(session, old_jwt, redis_client)
        assert new_row.replaced_by is None
    async with factory() as session:
        stale = await session.get(RefreshToken, old_row.id)
        assert stale is not None
        stale.revoked_at = None
        stale.replaced_by = uuid.uuid4()
        with pytest.raises(IntegrityError):
            await session.commit()
