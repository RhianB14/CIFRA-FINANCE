import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

API_DB = "cifra_test_accounts"
GATEWAY = "http://127.0.0.1:8001"

ENV: dict[str, str] = {}
ENV["ENVIRONMENT"] = "test"
ENV["DATABASE_URL"] = (
    "postgresql+asyncpg://cifra:cifra_local_development@localhost:5432/cifra_test_accounts"
)
ENV["REDIS_URL"] = "redis://localhost:6379/15"
ENV["JWT_SIGNING_KEY"] = "integration-" + "test-signing-key-0123456789abcdef0123456789abcdef"
ENV["TOTP_ENCRYPTION_KEY"] = "unit-test-fernet-key-placeholder-32b="
ENV["BACKUP_CODE_PEPPER"] = "integration-" + "test-pepper-0123456789abcdef0123456789abcdef"
ENV["CORS_ALLOWED_ORIGINS"] = "https://app.cifra.local"


def alembic_config(database: str) -> Config:
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

    from app.core.db import get_session
    from app.core.settings import get_settings as _gs
    from app.main import app as factory_app

    old = os.environ.copy()
    os.environ.update(ENV)
    _gs.cache_clear()

    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)

    async def override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
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
    factory_app.dependency_overrides.pop(get_session, None)


async def register_and_login(
    http: httpx.AsyncClient, email: str, password: str = "correct horse battery staple"
) -> str:
    response = await http.post(
        "/auth/register",
        json={"email": email, "name": "User", "password": password},
    )
    assert response.status_code in (200, 201), response.text
    login = await http.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    payload = login.json()
    return str(payload["access_token"])


def auth_headers(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio
async def test_account_crud_and_scope_isolation(client: httpx.AsyncClient) -> None:
    owner_access = await register_and_login(client, f"owner-{uuid.uuid4().hex[:8]}@example.com")
    intruder_access = await register_and_login(client, f"other-{uuid.uuid4().hex[:8]}@example.com")

    created = await client.post(
        "/accounts",
        json={
            "name": "Conta Principal",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
        headers=auth_headers(owner_access),
    )
    assert created.status_code in (200, 201), created.text
    account_id = created.json()["id"]

    listed = await client.get("/accounts", headers=auth_headers(owner_access))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    intruder_list = await client.get("/accounts", headers=auth_headers(intruder_access))
    assert intruder_list.status_code == 200
    assert intruder_list.json() == []

    fetched = await client.get(f"/accounts/{account_id}", headers=auth_headers(owner_access))
    assert fetched.status_code == 200
    assert fetched.json()["current_balance_cents"] == 100000

    intruder_get = await client.get(
        f"/accounts/{account_id}", headers=auth_headers(intruder_access)
    )
    assert intruder_get.status_code == 404

    renamed = await client.patch(
        f"/accounts/{account_id}",
        json={"name": "Conta Renomeada"},
        headers=auth_headers(owner_access),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Conta Renomeada"

    intruder_patch = await client.patch(
        f"/accounts/{account_id}",
        json={"name": "Hack"},
        headers=auth_headers(intruder_access),
    )
    assert intruder_patch.status_code == 404

    deleted = await client.delete(f"/accounts/{account_id}", headers=auth_headers(owner_access))
    assert deleted.status_code in (200, 204)

    after_delete = await client.get(f"/accounts/{account_id}", headers=auth_headers(owner_access))
    assert after_delete.status_code == 404


@pytest.mark.asyncio
async def test_account_validation_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    access = await register_and_login(client, f"valid-{uuid.uuid4().hex[:8]}@example.com")
    response = await client.post(
        "/accounts",
        json={"name": "X", "kind": "checking", "currency": "BRL", "is_admin": True},
        headers=auth_headers(access),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_accounts_require_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/accounts")
    assert response.status_code in (401, 403)
