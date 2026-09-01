import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from alembic import command
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.main import app
from tests.conftest import alembic_config

API_DB = "cifra_test_schemas"

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


class TestMassAssignment:
    async def test_register_rejects_unknown_fields(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "mass@example.com",
                "name": "Mass",
                "password": PASSWORD,
                "session_version": 99,
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["detail"][0]["type"] == "extra_forbidden"

    async def test_refresh_rejects_unknown_fields(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/auth/refresh", json={"refresh_token": "x", "sv": 7})
        assert response.status_code == 422
        assert response.json()["detail"][0]["type"] == "extra_forbidden"

    async def test_challenge_rejects_unknown_fields(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/auth/2fa/challenge", json={"challenge_id": "x", "totp": "000000", "admin": True}
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["type"] == "extra_forbidden"
