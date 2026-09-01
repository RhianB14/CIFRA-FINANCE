import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

API_DB = "cifra_test_pwreset"
GATEWAY = "http://127.0.0.1:8001"

ENV: dict[str, str] = {}
ENV["ENVIRONMENT"] = "test"
ENV["DATABASE_URL"] = (
    "postgresql+asyncpg://cifra:cifra_local_development@localhost:5432/cifra_test_pwreset"
)
ENV["REDIS_URL"] = "redis://localhost:6379/15"
ENV["JWT_SIGNING_KEY"] = "integration-" + "test-signing-key-0123456789abcdef0123456789abcdef"
ENV["TOTP_ENCRYPTION_KEY"] = "unit-test-fernet-key-placeholder-32b="
ENV["BACKUP_CODE_PEPPER"] = "integration-" + "test-pepper-0123456789abcdef0123456789abcdef"
ENV["CORS_ALLOWED_ORIGINS"] = "https://app.cifra.local"
ENV["PASSWORD_RESET_RESEND_ENABLED"] = "false"

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "brand new password value"


def alembic_config(database: str) -> "Config":
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://cifra:cifra_local_development@localhost:5432/{database}",
    )
    return cfg


async def make_api_database() -> None:
    import asyncpg

    admin = await asyncpg.connect("postgresql://cifra:cifra_local_development@localhost:5432/cifra")
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            API_DB,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{API_DB}"')
        await admin.execute(f'CREATE DATABASE "{API_DB}"')
    finally:
        await admin.close()


@pytest_asyncio.fixture()
async def api_engine() -> AsyncIterator[AsyncEngine]:
    await make_api_database()
    await asyncio.to_thread(command.upgrade, alembic_config(API_DB), "head")
    engine = create_async_engine(ENV["DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(api_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    import os

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.db import get_session
    from app.core.settings import get_settings as _gs
    from app.main import app as factory_app
    from app.services.mailer import get_mailer

    old = os.environ.copy()
    os.environ.update(ENV)
    _gs.cache_clear()
    get_mailer.cache_clear()

    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)

    async def override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            from app.core.db import set_bypass_scope

            await set_bypass_scope(session)
            yield session

    factory_app.dependency_overrides[get_session] = override

    transport = httpx.ASGITransport(app=factory_app)
    async with httpx.AsyncClient(
        transport=transport, base_url=GATEWAY, follow_redirects=False
    ) as http:
        yield http

    os.environ.clear()
    os.environ.update(old)
    _gs.cache_clear()
    get_mailer.cache_clear()
    factory_app.dependency_overrides.pop(get_session, None)


async def register_user(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Ana"},
    )
    assert response.status_code == 201


async def _latest_reset_token() -> str:
    store = redis.from_url(ENV["REDIS_URL"], decode_responses=True)
    try:
        keys = [key async for key in store.scan_iter(match="cifra:reset:*")]
        assert len(keys) == 1
        stored = await store.get(keys[0])
        assert isinstance(stored, str)
        return stored
    finally:
        await store.aclose()


class TestPasswordRecovery:
    async def test_recovery_answers_200_for_known_and_unknown_email(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        await register_user(client, "reset-known@example.com")
        known = await client.post(
            "/auth/password-recovery", json={"email": "reset-known@example.com"}
        )
        unknown = await client.post(
            "/auth/password-recovery", json={"email": "reset-ghost@example.com"}
        )
        assert known.status_code == 200
        assert unknown.status_code == 200
        assert known.content == unknown.content

    async def test_reset_with_issued_token_reauthenticates(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        await register_user(client, "reset-flow@example.com")
        await client.post("/auth/password-recovery", json={"email": "reset-flow@example.com"})
        token = await _latest_reset_token()
        reset = await client.post(
            "/auth/password-reset",
            json={"token": token, "new_password": NEW_PASSWORD},
        )
        assert reset.status_code == 200
        login = await client.post(
            "/auth/login", data={"username": "reset-flow@example.com", "password": NEW_PASSWORD}
        )
        assert login.status_code == 200
        old_login = await client.post(
            "/auth/login", data={"username": "reset-flow@example.com", "password": PASSWORD}
        )
        assert old_login.status_code == 401

    async def test_recovery_rate_limit_is_three_per_hour(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        for index in range(3):
            response = await client.post(
                "/auth/password-recovery", json={"email": f"rl-{index}@example.com"}
            )
            assert response.status_code == 200
        fourth = await client.post(
            "/auth/password-recovery", json={"email": "rl-fourth@example.com"}
        )
        assert fourth.status_code == 429
        assert "Retry-After" in fourth.headers
