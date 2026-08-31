from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.main import app

API_DB = "cifra_test_inactive"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


def admin_url() -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/postgres"


def db_url(database: str) -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/" + database


async def make_api_database() -> None:
    import asyncpg

    connection = await asyncpg.connect(admin_url().replace("postgresql+asyncpg", "postgresql"))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{API_DB}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{API_DB}"')
    finally:
        await connection.close()


def _create_all(sync_conn: Connection) -> None:
    from app.models import Base

    Base.metadata.create_all(sync_conn)


@pytest_asyncio.fixture()
async def api_engine() -> AsyncIterator[AsyncEngine]:
    await make_api_database()
    engine = create_async_engine(db_url(API_DB))
    async with engine.begin() as conn:
        await conn.run_sync(_create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(
    api_engine: AsyncEngine,
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]]:
    from app.core import db as db_module

    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)
    original_factory = db_module._session_factory
    db_module._session_factory = factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client, factory
    db_module._session_factory = original_factory


async def test_inactive_user_is_rejected_on_protected_routes(
    client: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, factory = client
    register = await http_client.post(
        "/auth/register",
        json={"email": "inactive@example.com", "password": PASSWORD, "name": "Inactive"},
    )
    assert register.status_code == 201
    tokens = register.json()

    from app.models import User

    me = await http_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200

    async with factory() as session:
        await session.execute(
            update(User).where(User.email == "inactive@example.com").values(is_active=False)
        )
        await session.commit()

    me_after = await http_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_after.status_code == 401
