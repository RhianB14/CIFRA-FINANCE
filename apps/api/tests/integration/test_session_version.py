import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import jwt as pyjwt
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
from app.core.tokens import decode_access_token
from app.main import app
from app.models import User
from app.services.rotation import ReuseDetectedError
from tests.conftest import alembic_config, async_url, recreate_database

VERSION_DB = "cifra_test_session_version"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def version_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(VERSION_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(VERSION_DB), "head")
    engine = create_async_engine(async_url(VERSION_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def version_factory(
    version_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(version_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture()
async def redis_client() -> AsyncIterator[redis.Redis]:
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture()
async def client(
    version_engine: AsyncEngine,
    redis_client: redis.Redis,
) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import db as db_module

    original_factory = db_module._session_factory
    db_module._session_factory = async_sessionmaker(
        version_engine, expire_on_commit=False, autoflush=False
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    db_module._session_factory = original_factory


async def register_user(client: httpx.AsyncClient, email: str) -> dict[str, object]:
    response = await client.post(
        "/auth/register", json={"email": email, "password": PASSWORD, "name": "Ana"}
    )
    assert response.status_code == 201
    return dict(response.json())


async def database_version(factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> int:
    session_version_column = vars(User)["session_version"]
    async with factory() as session:
        result = await session.execute(select(session_version_column).where(User.id == user_id))
        value = result.scalar_one()
        return int(value)


async def user_id_for(factory: async_sessionmaker[AsyncSession], email: str) -> uuid.UUID:
    async with factory() as session:
        result = await session.execute(select(User.id).where(User.email == email))
        return uuid.UUID(str(result.scalar_one()))


async def test_user_row_starts_with_session_version_one(
    version_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with version_factory() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            name="Ana",
            password_hash="x" * 20,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    assert vars(user)["session_version"] == 1


async def test_reuse_bumps_durable_session_version(
    version_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    from app.services.rotation import issue_refresh_token, rotate_refresh_token

    async with version_factory() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            name="Ana",
            password_hash="x" * 20,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        jwt, _ = await issue_refresh_token(session, user.id)
        await session.commit()
    assert await database_version(version_factory, user.id) == 1
    async with version_factory() as session:
        await rotate_refresh_token(session, jwt, redis_client)
    async with version_factory() as session:
        with pytest.raises(ReuseDetectedError):
            await rotate_refresh_token(session, jwt, redis_client)
    assert await database_version(version_factory, user.id) == 2


async def test_reuse_invalidates_old_access_and_new_login_works(
    client: httpx.AsyncClient,
    version_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    email = f"sv-{uuid.uuid4().hex}@example.com"
    body = await register_user(client, email)
    old_access = str(body["access_token"])
    refresh = str(body["refresh_token"])
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert me.status_code == 200

    first_reuse = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert first_reuse.status_code == 200
    reuse = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401

    old_me = await client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert old_me.status_code == 401

    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    access = str(login.json()["access_token"])
    payload = decode_access_token(access)
    assert payload["sv"] == 2
    me_after = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me_after.status_code == 200


async def test_refresh_after_reuse_emits_access_with_current_version(
    client: httpx.AsyncClient,
    redis_client: redis.Redis,
) -> None:
    email = f"sv2-{uuid.uuid4().hex}@example.com"
    body = await register_user(client, email)
    refresh = str(body["refresh_token"])
    await client.post("/auth/refresh", json={"refresh_token": refresh})
    reuse = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    new_refresh = str(login.json()["refresh_token"])
    rotated = await client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert rotated.status_code == 200
    payload = decode_access_token(str(rotated.json()["access_token"]))
    assert payload["sv"] == 2


async def test_redis_flush_does_not_resurrect_revoked_sessions(
    client: httpx.AsyncClient,
    version_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    email = f"flush-{uuid.uuid4().hex}@example.com"
    body = await register_user(client, email)
    old_access = str(body["access_token"])
    refresh = str(body["refresh_token"])
    await client.post("/auth/refresh", json={"refresh_token": refresh})
    reuse = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401
    await redis_client.flushdb()
    old_me = await client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert old_me.status_code == 401
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    payload = decode_access_token(str(login.json()["access_token"]))
    assert payload["sv"] == 2


async def test_redis_unavailable_returns_stable_503(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.session_revocation as revocation

    email = f"down-{uuid.uuid4().hex}@example.com"
    body = await register_user(client, email)
    access = str(body["access_token"])
    broken = redis.Redis(host="localhost", port=1, decode_responses=True)
    monkeypatch.setattr(revocation, "_default_client", lambda: broken)
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 503
    assert "unavailable" in str(me.json().get("detail", "")).lower()
    await broken.aclose()


async def test_concurrent_bumps_do_not_lose_increments(
    version_engine: AsyncEngine,
) -> None:
    import app.services.session_revocation as revocation

    bump_session_version = cast(Any, vars(revocation)["bump_session_version"])
    factory = async_sessionmaker(version_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            name="Ana",
            password_hash="x" * 20,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    rounds = 6

    async def bump() -> None:
        own = create_async_engine(async_url(VERSION_DB))
        try:
            own_factory = async_sessionmaker(own, expire_on_commit=False, autoflush=False)
            async with own_factory() as session:
                await bump_session_version(session, user.id)
                await session.commit()
        finally:
            await own.dispose()

    await asyncio.gather(*(bump() for _ in range(rounds)))
    assert await database_version(factory, user.id) == 1 + rounds


async def test_emission_uses_database_version_not_constant_one(
    version_factory: async_sessionmaker[AsyncSession],
    redis_client: redis.Redis,
) -> None:
    from app.services.auth import start_session

    async with version_factory() as session:
        user = User(
            email=f"{uuid.uuid4().hex}@example.com",
            name="Ana",
            password_hash="x" * 20,
            session_version=3,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        access, _ = await start_session(session, user)
    payload = pyjwt.decode(
        access,
        options={"verify_signature": False},
    )
    assert payload["sv"] == 3
