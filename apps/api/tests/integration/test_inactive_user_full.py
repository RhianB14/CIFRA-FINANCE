import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import db as db_module
from app.core.settings import get_settings
from app.main import app
from app.models import RefreshToken, User
from tests.conftest import alembic_config, async_url, recreate_database

INACTIVE_DB = "cifra_test_inactive_full"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def inactive_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(INACTIVE_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(INACTIVE_DB), "head")
    engine = create_async_engine(async_url(INACTIVE_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def environment(
    inactive_engine: AsyncEngine,
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]]:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    await store.flushdb()
    original = db_module._session_factory
    factory = async_sessionmaker(inactive_engine, expire_on_commit=False, autoflush=False)
    db_module._session_factory = factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value, factory
    db_module._session_factory = original
    await store.flushdb()
    await store.aclose()


async def deactivate(factory: async_sessionmaker[AsyncSession], email: str) -> None:
    async with factory() as session:
        await session.execute(update(User).where(User.email == email).values(is_active=False))
        await session.commit()


async def refresh_token_state(
    factory: async_sessionmaker[AsyncSession], email: str
) -> list[tuple[object, ...]]:
    async with factory() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
        assert user_id is not None
        rows = await session.execute(
            select(RefreshToken.id, RefreshToken.revoked_at, RefreshToken.replaced_by).where(
                RefreshToken.user_id == user_id
            )
        )
        return [(row[0], row[1], row[2]) for row in rows.all()]


async def register(environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]) -> str:
    http_client, _ = environment
    email = f"inactive-{uuid.uuid4().hex}@example.com"
    response = await http_client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Inactive"},
    )
    assert response.status_code == 201
    return email


async def activate_two_factor(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]], email: str
) -> None:
    http_client, _ = environment
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    tokens = dict(login.json())
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    setup = await http_client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    parsed = pyotp.parse_uri(str(setup.json()["otpauth_uri"]))
    assert isinstance(parsed, pyotp.TOTP)
    confirmed = await http_client.post(
        "/auth/2fa/verify", headers=headers, json={"code": parsed.now()}
    )
    assert confirmed.status_code == 200


async def test_inactive_login_is_indistinguishable_from_bad_credentials(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, _ = environment
    email = await register(environment)
    await deactivate(environment[1], email)
    inactive = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    unknown_user = await http_client.post(
        "/auth/login",
        data={"username": f"ghost-{uuid.uuid4().hex}@example.com", "password": PASSWORD},
    )
    assert inactive.status_code == unknown_user.status_code == 401
    assert inactive.json() == unknown_user.json()


async def test_inactive_refresh_is_rejected_without_touching_refresh_tokens(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, factory = environment
    email = await register(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    refresh = str(dict(login.json())["refresh_token"])
    await deactivate(factory, email)
    state_before = await refresh_token_state(factory, email)
    response = await http_client.post("/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    state_after = await refresh_token_state(factory, email)
    assert state_after == state_before


async def test_inactive_user_cannot_consume_pending_challenge(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, factory = environment
    email = await register(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    access = str(dict(login.json())["access_token"])
    headers = {"Authorization": f"Bearer {access}"}
    setup = await http_client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    parsed = pyotp.parse_uri(str(setup.json()["otpauth_uri"]))
    assert isinstance(parsed, pyotp.TOTP)
    confirmed = await http_client.post(
        "/auth/2fa/verify", headers=headers, json={"code": parsed.now()}
    )
    assert confirmed.status_code == 200
    backup_codes = list(confirmed.json()["backup_codes"])
    challenge_login = await http_client.post(
        "/auth/login", data={"username": email, "password": PASSWORD}
    )
    assert challenge_login.status_code == 200
    challenge = str(dict(challenge_login.json())["challenge_id"])
    await deactivate(factory, email)
    response = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": backup_codes[0]}
    )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert "access_token" not in response.text
    replay = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": backup_codes[0]}
    )
    assert replay.status_code == 401


async def test_inactive_user_cannot_use_2fa_management_routes(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, factory = environment
    email = await register(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    access = str(dict(login.json())["access_token"])
    headers = {"Authorization": f"Bearer {access}"}
    await deactivate(factory, email)
    setup = await http_client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 401
    verify = await http_client.post("/auth/2fa/verify", headers=headers, json={"code": "123456"})
    assert verify.status_code == 401
    disable = await http_client.post(
        "/auth/2fa/disable", headers=headers, json={"password": PASSWORD, "code": "123456"}
    )
    assert disable.status_code == 401
