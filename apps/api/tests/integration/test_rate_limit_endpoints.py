import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from alembic import command
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.main import app
from tests.conftest import alembic_config

API_DB = "cifra_test_ratelimit"

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


def _session_factory_for(api_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)


async def test_register_blocks_fourth_attempt_per_minute(
    client: httpx.AsyncClient,
) -> None:
    statuses = []
    for index in range(4):
        response = await client.post(
            "/auth/register",
            json={
                "email": f"rl-reg-{index}@example.com",
                "password": PASSWORD,
                "name": "Ana",
            },
        )
        statuses.append(response.status_code)
    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429


async def test_register_429_carries_retry_after_header(
    client: httpx.AsyncClient,
) -> None:
    for index in range(3):
        await client.post(
            "/auth/register",
            json={
                "email": f"rl-retry-{index}@example.com",
                "password": PASSWORD,
                "name": "Ana",
            },
        )
    response = await client.post(
        "/auth/register",
        json={"email": "rl-retry-3@example.com", "password": PASSWORD, "name": "Ana"},
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after", "").isdigit()


async def test_login_blocks_sixth_attempt_per_minute(
    client: httpx.AsyncClient,
) -> None:
    for index in range(5):
        response = await client.post(
            "/auth/login",
            data={"username": f"rl-login-{index}@example.com", "password": PASSWORD},
        )
        assert response.status_code == 401
    overflow = await client.post(
        "/auth/login",
        data={"username": "rl-login-overflow@example.com", "password": PASSWORD},
    )
    assert overflow.status_code == 429


async def test_login_429_carries_retry_after_header(
    client: httpx.AsyncClient,
) -> None:
    for index in range(5):
        await client.post(
            "/auth/login",
            data={"username": f"rl-retryl-{index}@example.com", "password": PASSWORD},
        )
    response = await client.post(
        "/auth/login",
        data={"username": "rl-retryl-final@example.com", "password": PASSWORD},
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after", "").isdigit()


async def test_register_429_returns_json_detail(client: httpx.AsyncClient) -> None:
    for index in range(4):
        response = await client.post(
            "/auth/register",
            json={
                "email": f"rl-json-{index}@example.com",
                "password": PASSWORD,
                "name": "Ana",
            },
        )
    assert response.status_code == 429
    assert "detail" in response.json()
