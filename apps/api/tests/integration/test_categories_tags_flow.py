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
async def ct_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        email = f"ct-{uuid.uuid4().hex[:10]}@example.com"
        password = "Str0ng!Pass123"
        response = await http.post(
            "/auth/register",
            json={"email": email, "name": "CT", "password": password},
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
async def test_categories_tags_crud_with_scope_isolation(ct_client: httpx.AsyncClient) -> None:
    created = await ct_client.post(
        "/categories",
        json={"name": "Mercado", "kind": "expense", "color": "#FFAA00"},
    )
    assert created.status_code == 201, created.text
    category = created.json()

    tags = await ct_client.post(
        "/tags",
        json={"name": "essencial"},
    )
    assert tags.status_code == 201, tags.text
    tag = tags.json()

    listed = await ct_client.get("/categories")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = await ct_client.patch(
        f"/categories/{category['id']}",
        json={"name": "Supermercado"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Supermercado"

    deleted = await ct_client.delete(f"/tags/{tag['id']}")
    assert deleted.status_code == 204

    tags_after = await ct_client.get("/tags")
    assert tags_after.status_code == 200
    assert len(tags_after.json()) == 0
