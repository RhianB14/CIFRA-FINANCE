import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import get_session
from app.main import app

DATABASE_URL = "postgresql+asyncpg://cifra:cifra_local_development@localhost:5432/cifra"


@pytest_asyncio.fixture
async def ol_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        email = f"ol-{uuid.uuid4().hex[:10]}@example.com"
        password = "Str0ng!Pass123"
        response = await http.post(
            "/auth/register",
            json={"email": email, "name": "OL", "password": password},
        )
        assert response.status_code in (200, 201), response.text
        login = await http.post(
            "/auth/login",
            data={"username": email, "password": password},
        )
        assert login.status_code == 200, login.text
        http.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield http
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_account_update_conflicts_on_stale_version(ol_client: httpx.AsyncClient) -> None:
    created = await ol_client.post(
        "/accounts",
        json={"name": "Conta OL", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201, created.text
    account = created.json()
    account_id = account["id"]

    stale = await ol_client.patch(
        f"/accounts/{account_id}",
        json={"name": "Renomeada", "expected_version": account["current_balance_version"]},
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["name"] == "Renomeada"

    replayed = await ol_client.patch(
        f"/accounts/{account_id}",
        json={"name": "Renomeada de novo", "expected_version": account["current_balance_version"]},
    )
    assert replayed.status_code == 409


@pytest.mark.asyncio
async def test_account_update_without_expected_version_uses_fresh_version(
    ol_client: httpx.AsyncClient,
) -> None:
    created = await ol_client.post(
        "/accounts",
        json={"name": "Conta Simples", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]
    updated = await ol_client.patch(
        f"/accounts/{account_id}",
        json={"name": "Outro nome"},
    )
    assert updated.status_code == 200, updated.text
