from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest

from app.main import app
from app.services.readiness import DependencyCheck, get_dependency_checks

CheckFactory = Callable[[], list[DependencyCheck]]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def override_checks() -> Iterator[Callable[[CheckFactory], None]]:
    def apply(factory: CheckFactory) -> None:
        app.dependency_overrides[get_dependency_checks] = factory

    yield apply

    app.dependency_overrides.clear()


async def healthy() -> None:
    return None


async def unavailable() -> None:
    raise ConnectionError("unavailable")


async def test_live_reports_process_is_alive(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "cifra-api"}


async def test_ready_reports_all_dependencies_as_healthy(
    client: httpx.AsyncClient, override_checks: Callable[[CheckFactory], None]
) -> None:
    override_checks(
        lambda: [
            DependencyCheck("postgres", healthy),
            DependencyCheck("redis", healthy),
            DependencyCheck("storage", healthy),
        ]
    )

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgres": "healthy", "redis": "healthy", "storage": "healthy"},
    }


async def test_ready_returns_503_when_dependency_is_unavailable(
    client: httpx.AsyncClient, override_checks: Callable[[CheckFactory], None]
) -> None:
    override_checks(
        lambda: [
            DependencyCheck("postgres", healthy),
            DependencyCheck("redis", unavailable),
            DependencyCheck("storage", healthy),
        ]
    )

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"postgres": "healthy", "redis": "unhealthy", "storage": "healthy"},
    }


async def test_dependency_overrides_are_empty_between_tests(client: httpx.AsyncClient) -> None:
    assert app.dependency_overrides == {}

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert app.dependency_overrides == {}
