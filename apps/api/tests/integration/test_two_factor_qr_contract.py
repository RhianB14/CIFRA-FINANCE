import asyncio
import base64
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.settings import get_settings
from app.core.totp import qr_data_uri
from app.main import app
from tests.conftest import alembic_config, async_url, recreate_database

QR_DB = "cifra_test_two_factor_qr"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def qr_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(QR_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(QR_DB), "head")
    engine = create_async_engine(async_url(QR_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(qr_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    await store.flushdb()
    original = db_module._session_factory
    db_module._session_factory = async_sessionmaker(
        qr_engine, expire_on_commit=False, autoflush=False
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
    db_module._session_factory = original
    await store.flushdb()
    await store.aclose()


async def test_setup_returns_decodable_qr_data_uri(client: httpx.AsyncClient) -> None:
    email = f"qr-{uuid.uuid4().hex}@example.com"
    registered = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Qr"},
    )
    assert registered.status_code == 201
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    payload = setup.json()
    assert payload["otpauth_uri"]
    qr = payload["qr_data_uri"]
    assert qr.startswith("data:image/png;base64,")
    encoded = qr.split(",", 1)[1]
    expected = qr_data_uri(str(payload["otpauth_uri"]))
    assert encoded == expected.split(",", 1)[1]
    base64.b64decode(encoded)
