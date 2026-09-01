import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pyotp
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

from app.core import db as db_module
from app.core.settings import get_settings
from app.main import app
from app.models import User
from tests.conftest import alembic_config, async_url, recreate_database

CHALLENGE_DB = "cifra_test_challenge_binding"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def challenge_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(CHALLENGE_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(CHALLENGE_DB), "head")
    engine = create_async_engine(async_url(CHALLENGE_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def environment(
    challenge_engine: AsyncEngine,
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis]]:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    await store.flushdb()
    original = db_module._session_factory
    factory = async_sessionmaker(challenge_engine, expire_on_commit=False, autoflush=False)
    db_module._session_factory = factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value, factory, store
    db_module._session_factory = original
    await store.flushdb()
    await store.aclose()


async def register_enrolled(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
) -> tuple[str, list[str]]:
    http_client, factory, _ = environment
    email = f"challenge-{uuid.uuid4().hex}@example.com"
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code in (200, 401)
    register = await http_client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Challenge"},
    )
    assert register.status_code == 201
    access = str(dict(register.json())["access_token"])
    headers = {"Authorization": f"Bearer {access}"}
    setup = await http_client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    parsed = pyotp.parse_uri(str(setup.json()["otpauth_uri"]))
    assert isinstance(parsed, pyotp.TOTP)
    confirmed = await http_client.post(
        "/auth/2fa/verify", headers=headers, json={"code": parsed.now()}
    )
    assert confirmed.status_code == 200
    return email, list(confirmed.json()["backup_codes"])


def make_broken_redis() -> redis.Redis:
    return redis.Redis(host="localhost", port=1, decode_responses=True)


async def test_challenge_survives_until_bump(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
) -> None:
    http_client, _, _ = environment
    email, codes = await register_enrolled(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    challenge = str(dict(login.json())["challenge_id"])
    consumed = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": codes[0]}
    )
    assert consumed.status_code == 200
    replay = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": codes[1]}
    )
    assert replay.status_code == 401


async def test_bump_invalidates_pending_challenge(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
) -> None:
    http_client, _, store = environment
    email, codes = await register_enrolled(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    challenge = str(dict(login.json())["challenge_id"])
    from app.services.rotation import revoke_all_refresh_tokens
    from app.services.session_revocation import bump_session_version

    async with environment[1]() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        await revoke_all_refresh_tokens(session, user.id)
        user.session_version = await bump_session_version(session, user.id)
        await session.commit()
    consumed = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge, "code": codes[0]}
    )
    assert consumed.status_code == 401


async def test_challenge_is_single_use_and_high_entropy(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
) -> None:
    http_client, _, store = environment
    email, codes = await register_enrolled(environment)
    login = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200
    challenge = str(dict(login.json())["challenge_id"])
    assert len(challenge) >= 32
    keys = [key async for key in store.scan_iter(match="cifra:2fa-challenge:*")]
    assert len(keys) == 1
    payload = json.loads(str(await store.get(keys[0])))
    assert payload["purpose"] == "login-2fa"
    assert payload["session_version"] >= 2
    assert payload["user_id"]


async def test_corrupted_challenge_payload_is_rejected_not_500(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
) -> None:
    http_client, _, store = environment
    challenge_id = uuid.uuid4().hex
    key = "cifra:2fa-challenge:" + challenge_id
    await store.set(key, "{not-valid-json")
    response = await http_client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge_id, "code": "123456"}
    )
    assert response.status_code == 401


async def test_unavailable_redis_returns_503_on_challenge_issue(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], redis.Redis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client, factory, _ = environment
    email, _ = await register_enrolled(environment)
    broken = make_broken_redis()

    def broken_from_url(*args: object, **kwargs: object) -> redis.Redis:
        return broken

    monkeypatch.setattr(redis, "from_url", broken_from_url)
    response = await http_client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 503
