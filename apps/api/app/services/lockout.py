from typing import Any, cast

from redis.asyncio import Redis

from app.core.settings import get_settings

LOCK_KEY_PREFIX = "cifra:lock:"
LOCK_WINDOW_MS = 15 * 60 * 1000
LOCK_TTL_SECONDS = 15 * 60
MAX_FAILURES = 5

LOCK_STATE_SCRIPT = """
local locked_until = tonumber(redis.call('HGET', KEYS[1], 'lock_until') or '0')
local now = tonumber(ARGV[1])
if locked_until > now then
  return 2
end
local failures = tonumber(redis.call('HGET', KEYS[1], 'failures') or '0')
local lock_count = tonumber(redis.call('HGET', KEYS[1], 'lock_count') or '0')
if tonumber(ARGV[2]) == 1 and failures >= tonumber(ARGV[3]) then
  lock_count = lock_count + 1
  local duration = tonumber(ARGV[4]) * (2 ^ (lock_count - 1))
  redis.call('HSET', KEYS[1],
    'lock_until', tostring(now + duration),
    'lock_count', tostring(lock_count))
  redis.call('PEXPIRE', KEYS[1], math.min(duration, 86400000))
  return 1
end
return 0
"""

REGISTER_SCRIPT = """
local failures = tonumber(redis.call('HINCRBY', KEYS[1], 'failures', 1))
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]))
if failures >= tonumber(ARGV[2]) then
  return failures
end
return 0
"""


async def _run_script(script: str, keys: list[str], args: list[object]) -> int:
    store: Redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        result = await cast(Any, store.eval(script, len(keys), *keys, *cast(Any, args)))
        return int(result)
    finally:
        await store.aclose()


async def is_locked(identity: str, now_ms: int | None = None) -> int:
    current = now_ms if now_ms is not None else _now_ms()
    try:
        return await _run_script(
            LOCK_STATE_SCRIPT, [_key(identity)], [current, 0, MAX_FAILURES, LOCK_WINDOW_MS]
        )
    except Exception:
        return 0


async def register_failure(identity: str, now_ms: int | None = None) -> int | None:
    try:
        return await _run_script(REGISTER_SCRIPT, [_key(identity)], [LOCK_WINDOW_MS, MAX_FAILURES])
    except Exception:
        return None


async def apply_lock(identity: str, now_ms: int | None = None) -> None:
    current = now_ms if now_ms is not None else _now_ms()
    try:
        await _run_script(
            LOCK_STATE_SCRIPT, [_key(identity)], [current, 1, MAX_FAILURES, LOCK_WINDOW_MS]
        )
    except Exception:
        return None


async def reset_failures(identity: str) -> None:
    try:
        store: Redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            await store.delete(_key(identity))
        finally:
            await store.aclose()
    except Exception:
        return None


def _key(identity: str) -> str:
    return LOCK_KEY_PREFIX + identity


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
