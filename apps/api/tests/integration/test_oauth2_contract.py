import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.settings import get_settings
from app.main import app
from tests.conftest import alembic_config, async_url, recreate_database

PASSWORD = "Tr0ub4dor&3-Correct-Horse"
OAUTH_DB = "cifra_test_oauth2"


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[httpx.AsyncClient]:
    await recreate_database(OAUTH_DB)
    await asyncio.to_thread(command.upgrade, alembic_config(OAUTH_DB), "head")
    engine: AsyncEngine = create_async_engine(async_url(OAUTH_DB))
    original = db_module._session_factory
    db_module._session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
    db_module._session_factory = original
    await engine.dispose()


async def test_oauth2_form_login_works(client: httpx.AsyncClient) -> None:
    email = "oauth2-form@example.com"
    registered = await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Ana"},
    )
    assert registered.status_code == 201
    login = await client.post(
        "/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


async def test_json_login_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert response.status_code == 422


async def test_authentication_401s_include_bearer_challenge(
    client: httpx.AsyncClient,
) -> None:
    invalid_login = await client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": PASSWORD},
    )
    missing_bearer = await client.get("/auth/me")
    invalid_bearer = await client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
    for response in (invalid_login, missing_bearer, invalid_bearer):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


async def test_openapi_declares_password_flow(client: httpx.AsyncClient) -> None:
    document = (await client.get("/openapi.json")).json()
    schemes = document["components"]["securitySchemes"]
    assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "auth/login"
    operation = document["paths"]["/auth/me"]["get"]
    assert {"OAuth2PasswordBearer": []} in operation["security"]
    assert get_settings().environment
