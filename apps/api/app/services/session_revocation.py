import uuid

import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models import User

VERSION_KEY_PREFIX = "cifra:session-version:"


class SessionStoreUnavailableError(Exception):
    pass


def _version_key(user_id: uuid.UUID) -> str:
    return VERSION_KEY_PREFIX + str(user_id)


def _default_client() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def _database_version(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(select(User.session_version).where(User.id == user_id))
    value = result.scalar_one_or_none()
    if value is None:
        return 0
    return int(value)


async def publish_session_version(
    user_id: uuid.UUID,
    session_version: int,
    client: redis.Redis | None = None,
) -> None:
    own = client is None
    store = client if client is not None else _default_client()
    try:
        await store.set(_version_key(user_id), session_version)
    except (RedisError, OSError) as error:
        raise SessionStoreUnavailableError("session dependency unavailable") from error
    finally:
        if own:
            await store.aclose()


async def session_invalid(
    session: AsyncSession,
    user_id: uuid.UUID,
    session_version: int,
    client: redis.Redis | None = None,
) -> bool:
    current = await _database_version(session, user_id)
    own = client is None
    store = client if client is not None else _default_client()
    try:
        cached = await store.get(_version_key(user_id))
        if cached is None or int(cached) != current:
            await store.set(_version_key(user_id), current)
    except (RedisError, OSError, ValueError) as error:
        raise SessionStoreUnavailableError("session dependency unavailable") from error
    finally:
        if own:
            await store.aclose()
    return current == 0 or session_version != current


async def bump_session_version(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(session_version=User.session_version + 1)
        .returning(User.session_version)
    )
    return int(result.scalar_one())
