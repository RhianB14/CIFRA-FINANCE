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


async def _make_account_with_deposit(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post(
        "/accounts",
        json={"name": "Conta OL", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    deposit = await client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": f"ol-dep-{uuid.uuid4().hex[:8]}",
            "operation_type": "deposit",
            "amount_cents": 10000,
            "occurred_at": "2026-09-02T12:00:00Z",
        },
    )
    assert deposit.status_code == 201, deposit.text
    return account_id, deposit.json()["id"]


@pytest.mark.asyncio
async def test_account_patch_conflicts_on_stale_balance_version(
    ol_client: httpx.AsyncClient,
) -> None:
    created = await ol_client.post(
        "/accounts",
        json={"name": "Conta Simples", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    stale = await ol_client.patch(
        f"/accounts/{account_id}",
        json={"name": "Renomeada", "expected_version": 99},
    )
    assert stale.status_code == 409

    fresh = await ol_client.patch(
        f"/accounts/{account_id}",
        json={"name": "Renomeada", "expected_version": 0},
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["name"] == "Renomeada"


@pytest.mark.asyncio
async def test_reversal_conflicts_on_stale_version_and_double_reversal(
    ol_client: httpx.AsyncClient,
) -> None:
    account_id, deposit_id = await _make_account_with_deposit(ol_client)

    stale = await ol_client.post(
        f"/accounts/{account_id}/transactions/{deposit_id}/reversal",
        json={"idempotency_key": f"ol-rev-{uuid.uuid4().hex[:8]}", "expected_version": 99},
    )
    assert stale.status_code == 409

    first = await ol_client.post(
        f"/accounts/{account_id}/transactions/{deposit_id}/reversal",
        json={"idempotency_key": f"ol-rev-a-{uuid.uuid4().hex[:8]}", "expected_version": 1},
    )
    assert first.status_code == 201, first.text

    double = await ol_client.post(
        f"/accounts/{account_id}/transactions/{deposit_id}/reversal",
        json={"idempotency_key": f"ol-rev-b-{uuid.uuid4().hex[:8]}", "expected_version": 2},
    )
    assert double.status_code == 409
