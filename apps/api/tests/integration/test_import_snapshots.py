import hashlib
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
async def imp_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        email = f"imp-{uuid.uuid4().hex[:10]}@example.com"
        password = "Str0ng!Pass123"
        response = await http.post(
            "/auth/register",
            json={"email": email, "name": "IMP", "password": password},
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


def _csv_payload() -> bytes:
    lines = [
        "external_id,occurred_at,description,amount_cents,kind",
        "tx-001,2026-09-01T10:00:00Z,Salario,500000,credit",
        "tx-002,2026-09-01T11:00:00Z,Mercado,12000,debit",
        "tx-003,2026-09-02T12:00:00Z,Assinatura,2990,debit",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_csv_import_is_idempotent_and_reconciliation_matches(
    imp_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    created = await imp_client.post(
        "/accounts",
        json={"name": "Conta Import", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    payload = _csv_payload()
    sha = hashlib.sha256(payload).hexdigest()

    first = await imp_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("extrato.csv", payload, "text/csv")},
        data={"source_name": "Banco X"},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["imported_count"] == 3
    assert body["skipped_count"] == 0
    assert body["file_sha256"] == sha

    second = await imp_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("extrato.csv", payload, "text/csv")},
        data={"source_name": "Banco X"},
    )
    assert second.status_code == 201, second.text
    body2 = second.json()
    assert body2["imported_count"] == 0
    assert body2["skipped_count"] == 3
    assert body2["file_sha256"] == sha

    listed = await imp_client.get(f"/accounts/{account_id}/transactions?limit=200")
    assert listed.status_code == 200
    assert len(listed.json()) == 3

    snapshot = await imp_client.post(
        f"/accounts/{account_id}/snapshots",
        json={"reported_balance_cents": 485010},
    )
    assert snapshot.status_code == 201, snapshot.text
    snap = snapshot.json()
    assert snap["ledger_balance_cents"] == 485010
    assert snap["difference_cents"] == 0
    assert snap["status"] == "matched"
