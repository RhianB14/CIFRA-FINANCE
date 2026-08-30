import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg
import httpx
import redis.asyncio as redis

from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    check: Callable[[], Awaitable[None]]


async def check_postgres(settings: Settings) -> None:
    connection = await asyncpg.connect(settings.database_url, timeout=3)
    try:
        await connection.execute("SELECT 1")
    finally:
        await connection.close()


async def check_redis(settings: Settings) -> None:
    client = redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def check_storage(settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f"{settings.s3_endpoint}/minio/health/ready")
        response.raise_for_status()


def get_dependency_checks() -> list[DependencyCheck]:
    settings = get_settings()
    return [
        DependencyCheck("postgres", lambda: check_postgres(settings)),
        DependencyCheck("redis", lambda: check_redis(settings)),
        DependencyCheck("storage", lambda: check_storage(settings)),
    ]


async def evaluate_readiness(checks: list[DependencyCheck]) -> dict[str, str]:
    results = await asyncio.gather(*(item.check() for item in checks), return_exceptions=True)
    return {
        item.name: "healthy" if not isinstance(result, BaseException) else "unhealthy"
        for item, result in zip(checks, results, strict=True)
    }
