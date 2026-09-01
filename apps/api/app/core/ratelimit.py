import ipaddress
from typing import Any

from redis.exceptions import RedisError

from app.core.settings import Settings, trusted_proxies_list

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1] * 1000)
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1] * 1000)
end
if current > tonumber(ARGV[2]) then
  if ttl < 0 then
    ttl = ARGV[1] * 1000
  end
  return {1, math.ceil(ttl / 1000)}
end
return {0, 0}
"""


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"rate limit exceeded, retry after {retry_after}s")


def client_ip(peer: str | None, forwarded: str | None, settings: Settings) -> str:
    peer_value = (peer or "").strip()
    forwarded_value = (forwarded or "").strip()
    if settings.trust_proxy_headers and peer_value:
        for proxy in trusted_proxies_list(settings):
            if proxy and peer_value == proxy:
                first = forwarded_value.split(",")[0].strip() if forwarded_value else ""
                try:
                    return str(ipaddress.ip_address(first))
                except ValueError:
                    return peer_value
    return peer_value if peer_value else "unknown"


async def check_rate_limit(
    store: Any,
    key: str,
    limit: int,
    window_seconds: int,
) -> int | None:
    try:
        result = await store.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            str(window_seconds),
            str(limit),
        )
    except RedisError:
        return None
    blocked, retry_after = int(result[0]), int(result[1])
    if blocked:
        raise RateLimitExceeded(max(1, retry_after))
    return None
