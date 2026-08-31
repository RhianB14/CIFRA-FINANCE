import uuid

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.settings import get_settings

VERSION_KEY_PREFIX = "cifra:session-version:"


class SessionStoreUnavailableError(Exception):
    pass


def _version_key(user_id: uuid.UUID) -> str:
    return VERSION_KEY_PREFIX + str(user_id)


def _default_client() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def get_global_version(
    user_id: uuid.UUID,
    client: redis.Redis | None = None,
) -> int:
    own = client is None
    r = client if client is not None else _default_client()
    try:
        value = await r.get(_version_key(user_id))
    except (RedisError, OSError) as error:
        raise SessionStoreUnavailableError(str(error)) from error
    finally:
        if own:
            await r.aclose()
    if value is None:
        return 1
    try:
        return max(1, int(value))
    except ValueError as error:
        raise SessionStoreUnavailableError("corrupt version value") from error


async def session_invalid(
    user_id: uuid.UUID,
    session_version: int,
    client: redis.Redis | None = None,
) -> bool:
    current = await get_global_version(user_id, client=client)
    return session_version < current


async def bump_global_version(user_id: uuid.UUID, client: redis.Redis | None = None) -> int:
    own = client is None
    r = client if client is not None else _default_client()
    try:
        result: int = await r.incr(_version_key(user_id))
        if result == 1:
            result = int(await r.incr(_version_key(user_id)))
    except (RedisError, OSError) as error:
        raise SessionStoreUnavailableError(str(error)) from error
    finally:
        if own:
            await r.aclose()
    return result
