import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as redis
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import db as db_module
from app.core.hibp import HIBPUnavailableError
from app.core.settings import get_settings
from app.main import app
from app.models import RefreshToken, User
from tests.conftest import alembic_config, async_url, recreate_database

HIBP_DB = "cifra_test_hibp_unavailable"
PASSWORD = "Tr0ub4dor&3-Correct-Horse"


@pytest_asyncio.fixture()
async def hibp_engine() -> AsyncIterator[AsyncEngine]:
    await recreate_database(HIBP_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(HIBP_DB), "head")
    engine = create_async_engine(async_url(HIBP_DB))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def environment(
    hibp_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]]:
    store = redis.from_url(get_settings().redis_url, decode_responses=True)
    await store.flushdb()
    original_factory = db_module._session_factory
    db_module._session_factory = async_sessionmaker(
        hibp_engine, expire_on_commit=False, autoflush=False
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "hibp_enabled", True)
    monkeypatch.setattr(settings, "hibp_timeout_seconds", 0.2)

    async def broken_transport(path: str, headers: dict[str, str], limit: float) -> str:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    monkeypatch.setattr("app.services.auth.http_hibp_transport", broken_transport)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value, db_module._session_factory
    db_module._session_factory = original_factory
    await store.flushdb()
    await store.aclose()


async def user_state(
    factory: async_sessionmaker[AsyncSession], email: str
) -> tuple[object, list[object]]:
    async with factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        tokens: list[object] = []
        if user is not None:
            rows = await session.execute(
                select(RefreshToken.id).where(RefreshToken.user_id == user.id)
            )
            tokens = list(rows.scalars())
        return user, tokens


async def test_unavailable_hibp_returns_503_without_persistence(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    http_client, factory = environment
    email = f"hibp-out-{uuid.uuid4().hex}@example.com"
    response = await http_client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Hibp"},
    )
    assert response.status_code == 503
    body = response.text
    assert "HIBP" not in body
    assert "pwnedpasswords" not in body
    assert PASSWORD not in body
    user, tokens = await user_state(factory, email)
    assert user is None
    assert tokens == []


async def test_unavailable_hibp_error_is_controlled_at_service_level(
    environment: tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]],
    db_session: AsyncSession,
) -> None:
    http_client, _ = environment
    email = f"hibp-svc-{uuid.uuid4().hex}@example.com"
    from app.services.auth import register_user

    with pytest.raises(HIBPUnavailableError):
        await register_user(db_session, email, PASSWORD, "Hibp")
