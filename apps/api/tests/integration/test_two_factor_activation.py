import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.settings import get_settings
from app.core.tokens import decode_access_token
from app.main import app
from tests.conftest import alembic_config, async_url, recreate_database

ACTIVATION_DB = "cifra_test_two_factor_activation"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def activation_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(ACTIVATION_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(ACTIVATION_DB), "head")
    engine = create_async_engine(async_url(ACTIVATION_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(activation_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    await store.flushdb()
    original = db_module._session_factory
    db_module._session_factory = async_sessionmaker(
        activation_engine, expire_on_commit=False, autoflush=False
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
    db_module._session_factory = original
    await store.flushdb()
    await store.aclose()


async def register(client: httpx.AsyncClient) -> tuple[str, dict[str, object]]:
    email = f"activation-{uuid.uuid4().hex}@example.com"
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Ana"},
    )
    assert response.status_code == 201
    return email, dict(response.json())


async def activate(client: httpx.AsyncClient, access: str) -> tuple[str, dict[str, object]]:
    headers = {"Authorization": f"Bearer {access}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    uri = str(setup.json()["otpauth_uri"])
    parsed = pyotp.parse_uri(uri)
    assert isinstance(parsed, pyotp.TOTP)
    code = parsed.now()
    confirmed = await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    assert confirmed.status_code == 200
    return code, dict(confirmed.json())


async def test_activation_invalidates_old_access_and_refresh(
    client: httpx.AsyncClient,
) -> None:
    _, original = await register(client)
    old_access = str(original["access_token"])
    old_refresh = str(original["refresh_token"])
    _, activated = await activate(client, old_access)
    old_me = await client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    old_rotation = await client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert old_me.status_code == 401
    assert old_rotation.status_code == 401
    new_access = str(activated["access_token"])
    assert decode_access_token(new_access)["sv"] == 2
    new_me = await client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert new_me.status_code == 200


async def test_enrollment_code_cannot_authenticate_same_step(
    client: httpx.AsyncClient,
) -> None:
    email, original = await register(client)
    code, _ = await activate(client, str(original["access_token"]))
    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    challenge = str(login.json()["challenge_id"])
    replay = await client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": code}
    )
    assert replay.status_code == 401


async def test_backup_codes_returned_only_on_confirmation(
    client: httpx.AsyncClient,
) -> None:
    _, original = await register(client)
    _, activated = await activate(client, str(original["access_token"]))
    backup_codes = activated["backup_codes"]
    assert isinstance(backup_codes, list)
    assert len(backup_codes) == 10
    new_access = str(activated["access_token"])
    second_setup = await client.post(
        "/auth/2fa/setup", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert second_setup.status_code == 409
    assert "backup_codes" not in second_setup.text
