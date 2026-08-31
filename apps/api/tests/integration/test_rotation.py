import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.core.tokens import create_refresh_token
from app.models import Base, RefreshToken, User
from app.services.rotation import (
    ReuseDetectedError,
    TokenExpiredError,
    TokenNotFoundError,
    issue_refresh_token,
    revoke_session,
    rotate_refresh_token,
)
from app.services.session_revocation import (
    SessionStoreUnavailableError,
    bump_global_version,
    get_global_version,
    session_invalid,
)

ROTATION_DB = "cifra_test_rotation"


def admin_dsn() -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/postgres"


def db_url(database: str) -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/" + database


@pytest_asyncio.fixture()
async def rotation_engine() -> AsyncIterator[AsyncEngine]:
    import asyncpg

    connection = await asyncpg.connect(admin_dsn().replace("postgresql+asyncpg", "postgresql"))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{ROTATION_DB}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{ROTATION_DB}"')
    finally:
        await connection.close()
    engine = create_async_engine(db_url(ROTATION_DB))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def session_factory(
    rotation_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(rotation_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture()
async def redis_client() -> AsyncIterator[redis.Redis]:
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


async def make_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        name="Ana",
        password_hash="x" * 20,
    )
    session.add(user)
    await session.commit()
    return user


async def list_tokens(session: AsyncSession, user_id: uuid.UUID) -> list[RefreshToken]:
    result = await session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))
    return list(result.scalars())


@pytest.mark.asyncio
async def test_issue_creates_active_token_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, row = await issue_refresh_token(session, user.id)
        assert row.revoked_at is None
        assert row.replaced_by is None
        assert row.user_id == user.id
        assert jwt.count(".") == 2


@pytest.mark.asyncio
async def test_normal_rotation_revokes_old_and_issues_new(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        old_jwt, old_row = await issue_refresh_token(session, user.id)
    async with session_factory() as session:
        new_jwt, new_row = await rotate_refresh_token(session, old_jwt, redis_client)
        assert new_jwt != old_jwt
        assert new_row.family_id == old_row.family_id
        assert new_row.revoked_at is None
        refreshed_old = await session.get(RefreshToken, old_row.id)
        assert refreshed_old is not None
        assert refreshed_old.revoked_at is not None
        assert refreshed_old.replaced_by == new_row.id


@pytest.mark.asyncio
async def test_second_use_of_rotated_token_detected(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        old_jwt, _ = await issue_refresh_token(session, user.id)
        await rotate_refresh_token(session, old_jwt, redis_client)
    async with session_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, old_jwt, redis_client)


@pytest.mark.asyncio
async def test_reuse_revokes_every_refresh_of_user(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        target_jwt, _ = await issue_refresh_token(session, user.id)
        other_family_jwt, _ = await issue_refresh_token(session, user.id)
        await rotate_refresh_token(session, target_jwt, redis_client)
    async with session_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, target_jwt, redis_client)
    async with session_factory() as session:
        tokens = await list_tokens(session, user.id)
        assert tokens
        assert all(token.revoked_at is not None for token in tokens)
        assert other_family_jwt


@pytest.mark.asyncio
async def test_reuse_bumps_global_version_invalidating_access_tokens(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, _ = await issue_refresh_token(session, user.id)
        await rotate_refresh_token(session, jwt, redis_client)
    assert await get_global_version(user.id) == 1
    async with session_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, jwt, redis_client)
    assert await get_global_version(user.id) == 2
    assert await session_invalid(user.id, 1) is True


@pytest.mark.asyncio
async def test_reuse_isolated_per_user(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        attacker = await make_user(session)
        victim = await make_user(session)
        attacker_jwt, _ = await issue_refresh_token(session, attacker.id)
        await rotate_refresh_token(session, attacker_jwt, redis_client)
        victim_jwt, _ = await issue_refresh_token(session, victim.id)
        await rotate_refresh_token(session, victim_jwt, redis_client)
    async with session_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, attacker_jwt, redis_client)
    assert await get_global_version(victim.id) == 1
    assert await session_invalid(victim.id, 1) is False


@pytest.mark.asyncio
async def test_concurrent_rotation_allows_single_winner(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, _ = await issue_refresh_token(session, user.id)

    async def attempt() -> str:
        async with session_factory() as session:
            _, new_row = await rotate_refresh_token(session, jwt, redis_client)
            return str(new_row.id)

    results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    successes = [r for r in results if isinstance(r, str)]
    reuses = [r for r in results if isinstance(r, ReuseDetectedError)]
    assert len(successes) == 1
    assert len(reuses) == 1
    async with session_factory() as session:
        tokens = await list_tokens(session, user.id)
        assert all(token.revoked_at is not None for token in tokens)


@pytest.mark.asyncio
async def test_expired_refresh_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, _ = await issue_refresh_token(
            session,
            user.id,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    async with session_factory() as session:
        with pytest.raises(TokenExpiredError):
            await rotate_refresh_token(session, jwt, redis_client)


@pytest.mark.asyncio
async def test_logout_revoked_token_rejected_on_rotation(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, row = await issue_refresh_token(session, user.id)
        await revoke_session(session, jwt)
    async with session_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, jwt, redis_client)


@pytest.mark.asyncio
async def test_logout_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        jwt, _ = await issue_refresh_token(session, user.id)
        await revoke_session(session, jwt)
        await revoke_session(session, jwt)
        tokens = await list_tokens(session, user.id)
        assert len(tokens) == 1
        assert tokens[0].revoked_at is not None
    assert await get_global_version(user.id) == 1


@pytest.mark.asyncio
async def test_unknown_refresh_token_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    async with session_factory() as session:
        user = await make_user(session)
        signed_but_never_issued = create_refresh_token(user.id, uuid.uuid4())
    async with session_factory() as session:
        with pytest.raises(TokenNotFoundError):
            await revoke_session(session, signed_but_never_issued)


@pytest.mark.asyncio
async def test_session_version_defaults_and_bump(redis_client: redis.Redis) -> None:
    user_id = uuid.uuid4()
    assert await get_global_version(user_id) == 1
    assert await session_invalid(user_id, 1) is False
    await bump_global_version(user_id)
    assert await get_global_version(user_id) == 2
    assert await session_invalid(user_id, 1) is True
    assert await session_invalid(user_id, 2) is False


@pytest.mark.asyncio
async def test_redis_unavailable_fails_closed() -> None:
    user_id = uuid.uuid4()
    broken = redis.Redis(host="localhost", port=1, decode_responses=True)
    with pytest.raises(SessionStoreUnavailableError):
        await get_global_version(user_id, client=broken)
    with pytest.raises(SessionStoreUnavailableError):
        await session_invalid(user_id, 1, client=broken)
