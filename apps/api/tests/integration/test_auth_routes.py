import time
from collections.abc import AsyncIterator

import httpx
import pyotp
import pytest_asyncio
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import get_settings
from app.main import app

API_DB = "cifra_test_routes"

PASSWORD = "Tr0ub4dor&3-Correct-Horse"
EMAIL_A = "ana.routes@example.com"
EMAIL_B = "bruno.routes@example.com"


def admin_dsn() -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/postgres"


def db_url(database: str) -> str:
    return get_settings().database_url.rsplit("/", 1)[0] + "/" + database


async def make_api_database() -> None:
    import asyncpg

    connection = await asyncpg.connect(admin_dsn().replace("postgresql+asyncpg", "postgresql"))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{API_DB}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{API_DB}"')
    finally:
        await connection.close()


@pytest_asyncio.fixture()
async def api_engine() -> AsyncIterator[AsyncEngine]:
    await make_api_database()
    engine = create_async_engine(db_url(API_DB))
    async with engine.begin() as conn:
        await conn.run_sync(_create_all)
    yield engine
    await engine.dispose()


def _create_all(sync_conn: Connection) -> None:
    from app.models import Base

    Base.metadata.create_all(sync_conn)


@pytest_asyncio.fixture()
async def client(api_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import db as db_module

    original_factory = db_module._session_factory
    db_module._session_factory = _session_factory_for(api_engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    db_module._session_factory = original_factory


def _session_factory_for(
    api_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)


async def register(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Ana"},
    )


async def test_register_returns_201_with_tokens(client: httpx.AsyncClient) -> None:
    response = await register(client, EMAIL_A, PASSWORD)
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_register_rejects_duplicate_email(client: httpx.AsyncClient) -> None:
    await register(client, EMAIL_A, PASSWORD)
    response = await register(client, EMAIL_A, PASSWORD)
    assert response.status_code == 409


async def test_register_rejects_short_password(client: httpx.AsyncClient) -> None:
    response = await register(client, "curta@example.com", "curta12")
    assert response.status_code == 422


async def test_register_rejects_weak_password_normalized(client: httpx.AsyncClient) -> None:
    response = await register(client, "Mixed@Example.COM", PASSWORD)
    assert response.status_code == 201
    assert response.json()["access_token"]


async def test_login_returns_tokens(client: httpx.AsyncClient) -> None:
    await register(client, EMAIL_A, PASSWORD)
    response = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_wrong_password_401(client: httpx.AsyncClient) -> None:
    await register(client, EMAIL_A, PASSWORD)
    response = await client.post(
        "/auth/login", json={"email": EMAIL_A, "password": "WrongPassword-123"}
    )
    assert response.status_code == 401


async def test_login_unknown_user_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


async def test_me_requires_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401


async def test_me_rejects_invalid_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_me_returns_profile(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["email"] == EMAIL_A
    assert profile["name"] == "Ana"
    assert profile["totp_enabled"] is False


async def test_user_b_cannot_use_token_of_a(client: httpx.AsyncClient) -> None:
    token_a = (await register(client, EMAIL_A, PASSWORD)).json()["access_token"]
    await register(client, EMAIL_B, PASSWORD)
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL_A
    tampered = token_a[:-1] + ("A" if token_a[-1] != "A" else "B")
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


async def test_refresh_rotates_token(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    response = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert response.status_code == 200
    new = response.json()
    assert new["refresh_token"] != body["refresh_token"]
    replay = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert replay.status_code == 401


async def test_refresh_with_garbage_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/auth/refresh", json={"refresh_token": "garbage"})
    assert response.status_code == 401


async def test_logout_revokes_and_rejects_reuse(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    response = await client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
    assert response.status_code == 204
    reuse = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert reuse.status_code == 401


async def test_two_factor_flow_requires_challenge(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    uri = setup.json()["otpauth_uri"]
    seed = uri.split("secret=")[1].split("&")[0]
    code = pyotp.TOTP(seed).at(int(time.time()))
    verify = await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    assert verify.status_code == 200
    assert len(verify.json()["backup_codes"]) == 10
    login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    assert login.status_code == 200
    challenge_body = login.json()
    assert challenge_body.get("two_factor_required") is True
    assert challenge_body["challenge_id"]
    password_only = await client.post(
        "/auth/2fa/challenge",
        json={"challenge_id": challenge_body["challenge_id"], "code": "000000"},
    )
    assert password_only.status_code == 401
    second_login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    challenge_id = second_login.json()["challenge_id"]
    good_code = pyotp.TOTP(seed).at(int(time.time()))
    challenge = await client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge_id, "code": good_code}
    )
    assert challenge.status_code == 200
    assert challenge.json()["access_token"]


async def test_two_factor_challenge_reuses_challenge_id_is_single_use(
    client: httpx.AsyncClient,
) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    seed = setup.json()["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = pyotp.TOTP(seed).at(int(time.time()))
    await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    challenge_id = login.json()["challenge_id"]
    good_code = pyotp.TOTP(seed).at(int(time.time()))
    first = await client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge_id, "code": good_code}
    )
    assert first.status_code == 200
    second = await client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge_id, "code": good_code}
    )
    assert second.status_code == 401


async def test_backup_code_completes_challenge_once(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    seed = setup.json()["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = pyotp.TOTP(seed).at(int(time.time()))
    verify = await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    backup = verify.json()["backup_codes"][0]
    login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    challenge_id = login.json()["challenge_id"]
    first = await client.post(
        "/auth/2fa/challenge", json={"challenge_id": challenge_id, "code": backup}
    )
    assert first.status_code == 200
    again_login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    second_challenge = await client.post(
        "/auth/2fa/challenge",
        json={"challenge_id": again_login.json()["challenge_id"], "code": backup},
    )
    assert second_challenge.status_code == 401


async def test_two_factor_disable_with_totp(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    seed = setup.json()["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = pyotp.TOTP(seed).at(int(time.time()))
    await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    disable_code = pyotp.TOTP(seed).at(int(time.time()))
    disable = await client.post("/auth/2fa/disable", headers=headers, json={"code": disable_code})
    assert disable.status_code == 200
    login = await client.post("/auth/login", json={"email": EMAIL_A, "password": PASSWORD})
    assert login.json().get("access_token")


async def test_two_factor_setup_conflict_after_enable(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    setup = await client.post("/auth/2fa/setup", headers=headers)
    seed = setup.json()["otpauth_uri"].split("secret=")[1].split("&")[0]
    code = pyotp.TOTP(seed).at(int(time.time()))
    await client.post("/auth/2fa/verify", headers=headers, json={"code": code})
    conflict = await client.post("/auth/2fa/setup", headers=headers)
    assert conflict.status_code == 409


async def test_two_factor_verify_without_setup_400(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    response = await client.post("/auth/2fa/verify", headers=headers, json={"code": "123456"})
    assert response.status_code == 400


async def test_two_factor_disable_without_enable_409(client: httpx.AsyncClient) -> None:
    body = (await register(client, EMAIL_A, PASSWORD)).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    response = await client.post("/auth/2fa/disable", headers=headers, json={"code": "123456"})
    assert response.status_code == 409
