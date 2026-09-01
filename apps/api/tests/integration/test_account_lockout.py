import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.main import app
from tests.conftest import alembic_config

API_DB = "cifra_test_lockout"

PASSWORD = "Tr0ub4dor&3-Correct-Horse"


def db_url(database: str) -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/" + database


async def make_api_database() -> None:
    import asyncpg

    admin = db_url("postgres").replace("postgresql+asyncpg", "postgresql")
    connection = await asyncpg.connect(admin)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{API_DB}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{API_DB}"')
    finally:
        await connection.close()


@pytest_asyncio.fixture()
async def api_engine() -> AsyncIterator[AsyncEngine]:
    await make_api_database()
    await asyncio.to_thread(command.upgrade, alembic_config(API_DB), "head")
    engine = create_async_engine(db_url(API_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(api_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import db as db_module

    original_factory = db_module._session_factory
    db_module._session_factory = async_sessionmaker(
        api_engine, expire_on_commit=False, autoflush=False
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    db_module._session_factory = original_factory


@pytest.fixture(autouse=True)
def disable_rate_limit_for_lockout_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import auth as auth_module

    async def no_limit(request: object, bucket: str, limit: int) -> None:
        return None

    monkeypatch.setattr(auth_module, "_enforce_rate_limit", no_limit)
    asyncio.run(_flush_lock_db())


async def _flush_lock_db() -> None:
    store = lock_store()
    try:
        await store.flushdb()
    finally:
        await store.aclose()


def lock_store() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def register_user(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Ana"},
    )
    assert response.status_code == 201


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/auth/login", data={"username": email, "password": password})


async def test_five_failures_lock_account_even_with_correct_password(
    client: httpx.AsyncClient,
) -> None:
    email = "lock-five@example.com"
    await register_user(client, email)
    for _ in range(5):
        response = await login(client, email, "WrongPassword-123")
        assert response.status_code == 401
    correct = await login(client, email, PASSWORD)
    assert correct.status_code == 401
    store = lock_store()
    try:
        keys = []
        async for key in store.scan_iter(match="cifra:lock:*"):
            keys.append(key)
        assert len(keys) == 1
        ttl = await store.ttl(keys[0])
        assert 0 < ttl <= 900
    finally:
        await store.aclose()


async def test_lock_expires_and_login_succeeds_again(client: httpx.AsyncClient) -> None:
    email = "lock-expire@example.com"
    await register_user(client, email)
    for _ in range(5):
        await login(client, email, "WrongPassword-123")
    store = lock_store()
    try:
        keys = [key async for key in store.scan_iter(match="cifra:lock:*")]
        assert len(keys) == 1
        await cast(Any, store.hset(keys[0], "lock_until", str(int(time.time() * 1000) - 1)))
    finally:
        await store.aclose()
    response = await login(client, email, PASSWORD)
    assert response.status_code == 200


async def test_recidivism_doubles_lock_duration(client: httpx.AsyncClient) -> None:
    email = "lock-double@example.com"
    await register_user(client, email)
    for _ in range(5):
        await login(client, email, "WrongPassword-123")
    store = lock_store()
    try:
        keys = [key async for key in store.scan_iter(match="cifra:lock:*")]
        assert len(keys) == 1
        await cast(Any, store.hset(keys[0], "lock_until", str(int(time.time() * 1000) - 1)))
        await cast(Any, store.expire(keys[0], 3600))
    finally:
        await store.aclose()
    await login(client, email, "WrongPassword-123")
    store = lock_store()
    try:
        keys = [key async for key in store.scan_iter(match="cifra:lock:*")]
        assert len(keys) == 1
        ttl = await store.ttl(keys[0])
        assert 900 < ttl <= 1800
    finally:
        await store.aclose()


async def test_success_resets_failure_counter(client: httpx.AsyncClient) -> None:
    email = "lock-reset@example.com"
    await register_user(client, email)
    for _ in range(4):
        await login(client, email, "WrongPassword-123")
    ok = await login(client, email, PASSWORD)
    assert ok.status_code == 200
    for _ in range(4):
        await login(client, email, "WrongPassword-123")
    still_open = await login(client, email, PASSWORD)
    assert still_open.status_code == 200


async def test_locked_response_is_indistinguishable_from_bad_credentials(
    client: httpx.AsyncClient,
) -> None:
    email = "lock-shape@example.com"
    await register_user(client, email)
    wrong = await login(client, email, "WrongPassword-123")
    for _ in range(4):
        await login(client, email, "WrongPassword-123")
    locked = await login(client, email, PASSWORD)
    assert wrong.status_code == locked.status_code == 401
    assert wrong.json() == locked.json()
    assert dict(wrong.headers) == dict(locked.headers)


async def test_nonexistent_email_never_locks_real_accounts(
    client: httpx.AsyncClient,
) -> None:
    email = "lock-ghost@example.com"
    await register_user(client, email)
    for _ in range(8):
        response = await login(client, "ghost-unknown@example.com", PASSWORD)
        assert response.status_code == 401
    response = await login(client, email, PASSWORD)
    assert response.status_code == 200


async def test_lockout_store_unavailable_never_breaks_login(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import lockout as lockout_module

    async def broken_run(script: str, keys: list[str], args: list[object]) -> int:
        raise RuntimeError("store down")

    monkeypatch.setattr(lockout_module, "_run_script", broken_run)
    email = "lock-failopen@example.com"
    await register_user(client, email)
    response = await login(client, email, PASSWORD)
    assert response.status_code == 200
