import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

API_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.environ.get("POSTGRES_USER", "cifra")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "cifra_local_development")
PERSISTENCE_DB = "cifra_test_persistence"
MIGRATION_DB = "cifra_test_migration"
F1_TABLES = ("users", "refresh_tokens", "backup_codes", "audit_events")


def admin_dsn(database: str) -> str:
    return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{database}"


def async_url(database: str) -> str:
    return f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{database}"


async def recreate_database(database: str) -> None:
    connection = await asyncpg.connect(admin_dsn("postgres"))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


def alembic_config(database: str) -> Config:
    configuration = Config(str(API_ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(API_ROOT / "migrations"))
    configuration.set_main_option("sqlalchemy.url", async_url(database))
    return configuration


async def table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
            return {str(row[0]) for row in result}
    finally:
        await engine.dispose()


os.environ["DATABASE_URL"] = async_url(PERSISTENCE_DB)
os.environ.setdefault("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "https://app.cifra.local")
os.environ.setdefault("JWT_SIGNING_KEY", "unit-test-signing-key-0123456789abcdef0123456789abcdef")
os.environ.setdefault("TOTP_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault(
    "BACKUP_CODE_PEPPER", "unit-test-backup-pepper-0123456789abcdef0123456789abcdef"
)


@pytest.fixture(scope="session")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(PERSISTENCE_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(PERSISTENCE_DB), "head")
    engine = create_async_engine(
        async_url(PERSISTENCE_DB),
        connect_args={"server_settings": {"role": "cifra_app"}},
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        from app.core.db import set_bypass_scope

        await set_bypass_scope(session)
        yield session
    admin_engine = create_async_engine(async_url(PERSISTENCE_DB))
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(text("TRUNCATE " + ", ".join(F1_TABLES) + " CASCADE"))
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="session")
async def storage_ready() -> AsyncIterator[None]:
    from app.services.storage import ObjectStorage

    storage = ObjectStorage()
    await storage.ensure_bucket()
    yield


@pytest.fixture(autouse=True)
async def _clean_rate_limit_keys() -> AsyncIterator[None]:
    client = redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/15"), decode_responses=True
    )
    try:
        await client.delete(
            "cifra:ratelimit:register:testclient", "cifra:ratelimit:login:testclient"
        )
        yield
    finally:
        keys = []
        async for key in client.scan_iter(match="cifra:ratelimit:*"):
            keys.append(key)
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def register_and_login(http: httpx.AsyncClient) -> str:
    email = f"http-flow-{uuid.uuid4().hex[:10]}@example.com"
    password = "Str0ng!Pass123"
    response = await http.post(
        "/auth/register",
        json={"email": email, "name": "Http Flow", "password": password},
    )
    assert response.status_code in (200, 201), response.text
    login = await http.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


@pytest_asyncio.fixture
async def tx_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(async_url(PERSISTENCE_DB), poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    from app.core.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        token = await register_and_login(http)
        http.headers["Authorization"] = f"Bearer {token}"
        yield http
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()
