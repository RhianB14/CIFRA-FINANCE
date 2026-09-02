import io
import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import get_session

os.environ.setdefault("S3_ACCESS_KEY", "cifra_local")
os.environ.setdefault("S3_SECRET_KEY", "cifra_local_development")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
from app.main import app


@pytest.fixture
async def att_maker(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    maker = async_sessionmaker(migrated_engine, expire_on_commit=False)
    yield maker


@pytest_asyncio.fixture
async def att_client(
    att_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        async with att_maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        email = f"att-{uuid.uuid4().hex[:8]}@example.com"
        await http.post(
            "/auth/register",
            json={"email": email, "name": "User", "password": "correct horse battery staple"},
        )
        login = await http.post(
            "/auth/login",
            data={"username": email, "password": "correct horse battery staple"},
        )
        token = login.json()["access_token"]
        http.headers["Authorization"] = f"Bearer {token}"
        created = await http.post(
            "/accounts",
            json={
                "name": "Conta Anexos",
                "kind": "checking",
                "currency": "BRL",
                "initial_balance_cents": 0,
            },
        )
        assert created.status_code == 201, created.text
        yield http
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_attachment_upload_download(
    storage_ready: None, att_client: httpx.AsyncClient
) -> None:
    payload = b"receipt bytes"
    missing = await att_client.post(
        "/accounts/00000000-0000-0000-0000-000000000000/attachments",
        files={"file": ("receipt.bin", io.BytesIO(payload), "application/octet-stream")},
    )
    assert missing.status_code == 404

    account_id = (await att_client.get("/accounts")).json()[0]["id"]
    uploaded = await att_client.post(
        f"/accounts/{account_id}/attachments",
        files={"file": ("receipt.bin", io.BytesIO(payload), "application/octet-stream")},
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    assert attachment["file_name"] == "receipt.bin"

    downloaded = await att_client.get(f"/accounts/{account_id}/attachments/{attachment['id']}")
    assert downloaded.status_code == 200
    assert downloaded.content == payload
