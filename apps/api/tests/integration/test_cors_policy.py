import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings, ensure_secure_configuration, get_settings
from app.main import app
from tests.conftest import alembic_config

API_DB = "cifra_test_cors"


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


class TestCorsPolicy:
    async def test_unknown_origin_gets_no_cors_headers(self, client: httpx.AsyncClient) -> None:
        response = await client.options(
            "/auth/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    async def test_whitelisted_origin_is_reflected(self, client: httpx.AsyncClient) -> None:
        response = await client.options(
            "/auth/login",
            headers={
                "Origin": "https://app.cifra.local",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://app.cifra.local"

    async def test_production_requires_explicit_whitelist(self) -> None:
        settings = Settings(
            environment="production",
            jwt_signing_key="unit-test-signing-key-0123456789abcdef0123456789abcdef",
            totp_encryption_key="unit-test-field-key-0123456789abcdef0123456789ab",
            backup_code_pepper="unit-test-backup-pepper-0123456789abcdef0123456789abcdef",
            redis_url="redis://localhost:6379/15",
            database_url="postgresql+asyncpg://cifra:pw@localhost:5432/db",
            cors_allowed_origins="",
        )
        with pytest.raises(RuntimeError) as excinfo:
            ensure_secure_configuration(settings)
        assert "cors_allowed_origins" in str(excinfo.value)
