import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.settings import Settings
from app.services.readiness import (
    DependencyCheck,
    check_postgres,
    check_redis,
    check_storage,
    evaluate_readiness,
)


async def successful() -> None:
    return None


async def failing() -> None:
    raise ConnectionError("unavailable")


async def test_postgres_success_executes_probe_and_closes_connection() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock()
    connection.close = AsyncMock()

    with patch("app.services.readiness.asyncpg.connect", AsyncMock(return_value=connection)):
        await check_postgres(Settings(database_url="postgresql://test"))

    connection.execute.assert_awaited_once_with("SELECT 1")
    connection.close.assert_awaited_once()


async def test_postgres_failure_still_closes_connection() -> None:
    connection = MagicMock()
    connection.execute = AsyncMock(side_effect=RuntimeError("query failed"))
    connection.close = AsyncMock()

    with (
        patch("app.services.readiness.asyncpg.connect", AsyncMock(return_value=connection)),
        pytest.raises(RuntimeError, match="query failed"),
    ):
        await check_postgres(Settings(database_url="postgresql://test"))

    connection.close.assert_awaited_once()


async def test_redis_success_pings_and_closes_client() -> None:
    client = MagicMock()
    client.ping = AsyncMock()
    client.aclose = AsyncMock()

    with patch("app.services.readiness.redis.from_url", return_value=client) as from_url:
        await check_redis(Settings(redis_url="redis://test"))

    from_url.assert_called_once_with("redis://test", socket_connect_timeout=3, socket_timeout=3)
    client.ping.assert_awaited_once()
    client.aclose.assert_awaited_once()


async def test_redis_false_ping_closes_client() -> None:
    client = MagicMock()
    client.ping.return_value = False
    client.aclose = AsyncMock()

    with (
        patch("app.services.readiness.redis.from_url", return_value=client),
        pytest.raises(ConnectionError, match="Redis ping failed"),
    ):
        await check_redis(Settings(redis_url="redis://test"))

    client.aclose.assert_awaited_once()


async def test_redis_async_false_ping_closes_client() -> None:
    client = MagicMock()
    client.ping = AsyncMock(return_value=False)
    client.aclose = AsyncMock()

    with (
        patch("app.services.readiness.redis.from_url", return_value=client),
        pytest.raises(ConnectionError, match="Redis ping failed"),
    ):
        await check_redis(Settings(redis_url="redis://test"))

    client.aclose.assert_awaited_once()


async def test_redis_failure_still_closes_client() -> None:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=ConnectionError("ping failed"))
    client.aclose = AsyncMock()

    with (
        patch("app.services.readiness.redis.from_url", return_value=client),
        pytest.raises(ConnectionError, match="ping failed"),
    ):
        await check_redis(Settings(redis_url="redis://test"))

    client.aclose.assert_awaited_once()


async def test_storage_success_uses_readiness_endpoint() -> None:
    response = MagicMock()
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client

    with patch("app.services.readiness.httpx.AsyncClient", return_value=context):
        await check_storage(Settings(s3_endpoint="http://storage"))

    client.get.assert_awaited_once_with("http://storage/minio/health/ready")
    response.raise_for_status.assert_called_once()


async def test_storage_propagates_non_ready_response() -> None:
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "not ready",
        request=httpx.Request("GET", "http://storage/minio/health/ready"),
        response=httpx.Response(503),
    )
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client

    with (
        patch("app.services.readiness.httpx.AsyncClient", return_value=context),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await check_storage(Settings(s3_endpoint="http://storage"))


async def test_readiness_evaluates_dependencies_in_parallel() -> None:
    started: set[str] = set()
    release = asyncio.Event()

    async def wait_for_others(name: str) -> None:
        started.add(name)
        if len(started) == 3:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)

    def create_check(name: str) -> DependencyCheck:
        async def check() -> None:
            await wait_for_others(name)

        return DependencyCheck(name, check)

    checks = [create_check(name) for name in ("postgres", "redis", "storage")]

    result = await evaluate_readiness(checks)

    assert result == {"postgres": "healthy", "redis": "healthy", "storage": "healthy"}


def test_dependency_checks_use_current_settings() -> None:
    settings = Settings()

    with patch("app.services.readiness.get_settings", return_value=settings):
        from app.services.readiness import get_dependency_checks

        checks = get_dependency_checks()

    assert [check.name for check in checks] == ["postgres", "redis", "storage"]


async def test_readiness_maps_failures_without_cancelling_healthy_checks() -> None:
    checks = [DependencyCheck("postgres", successful), DependencyCheck("redis", failing)]

    result = await evaluate_readiness(checks)

    assert result == {"postgres": "healthy", "redis": "unhealthy"}


def test_dependency_check_accepts_async_callable() -> None:
    check = DependencyCheck("postgres", successful)

    assert check.name == "postgres"
    assert callable(check.check)


def test_settings_can_be_created_without_environment_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(**cast(Any, {"_env_file": None}))

    assert isinstance(settings.database_url, str)


def consume_any(value: Any) -> Any:
    return value
