import pytest
import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.ratelimit import RateLimitExceeded, check_rate_limit
from app.core.settings import Settings, ensure_secure_configuration

REDIS_URL = "redis://localhost:6379/15"


def _settings(**overrides: object) -> Settings:
    base = Settings(environment="test")
    return base.model_copy(update=overrides)


def test_direct_peer_is_used_by_default_even_with_forwarded_header() -> None:
    from app.core.ratelimit import client_ip

    settings = _settings()
    assert client_ip("10.0.0.5", "203.0.113.9", settings) == "10.0.0.5"


def test_trusted_proxy_allows_forwarded_claim() -> None:
    from app.core.ratelimit import client_ip

    settings = _settings(trust_proxy_headers=True, trusted_proxies="10.0.0.5,10.0.0.6")
    assert client_ip("10.0.0.5", "203.0.113.9, 10.0.0.5", settings) == "203.0.113.9"


def test_unlisted_proxy_is_not_trusted() -> None:
    from app.core.ratelimit import client_ip

    settings = _settings(trust_proxy_headers=True, trusted_proxies="10.0.0.99")
    assert client_ip("10.0.0.5", "203.0.113.9", settings) == "10.0.0.5"


def test_invalid_forwarded_claim_falls_back_to_peer() -> None:
    from app.core.ratelimit import client_ip

    settings = _settings(trust_proxy_headers=True, trusted_proxies="10.0.0.5")
    assert client_ip("10.0.0.5", "not-an-ip", settings) == "10.0.0.5"
    assert client_ip("10.0.0.5", None, settings) == "10.0.0.5"


def test_missing_peer_uses_unknown_bucket() -> None:
    from app.core.ratelimit import client_ip

    settings = _settings()
    assert client_ip(None, None, settings) == "unknown"


def test_trust_without_proxy_list_is_rejected_at_startup() -> None:
    settings = _settings(trust_proxy_headers=True, trusted_proxies="")
    with pytest.raises(RuntimeError):
        ensure_secure_configuration(settings)


async def test_check_rate_limit_allows_until_limit_then_blocks() -> None:
    store = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await store.delete("ratelimit:test:until-limit")
        for _ in range(3):
            check = await check_rate_limit(store, "ratelimit:test:until-limit", 3, 60)
            assert check is None
        with pytest.raises(RateLimitExceeded) as error:
            await check_rate_limit(store, "ratelimit:test:until-limit", 3, 60)
        assert 0 < error.value.retry_after <= 60
    finally:
        await store.delete("ratelimit:test:until-limit")
        await store.aclose()


async def test_check_rate_limit_sets_bounded_ttl_once() -> None:
    store = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await store.delete("ratelimit:test:ttl")
        await check_rate_limit(store, "ratelimit:test:ttl", 5, 60)
        ttl = await store.ttl("ratelimit:test:ttl")
        assert 0 < ttl <= 60
    finally:
        await store.delete("ratelimit:test:ttl")
        await store.aclose()


async def test_check_rate_limit_window_expires_and_key_is_removed() -> None:
    store = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await store.delete("ratelimit:test:expire")
        await check_rate_limit(store, "ratelimit:test:expire", 1, 1)
        with pytest.raises(RateLimitExceeded):
            await check_rate_limit(store, "ratelimit:test:expire", 1, 1)
        import asyncio

        await asyncio.sleep(1.1)
        assert await store.exists("ratelimit:test:expire") == 0
        assert await check_rate_limit(store, "ratelimit:test:expire", 1, 1) is None
    finally:
        await store.delete("ratelimit:test:expire")
        await store.aclose()


async def test_check_rate_limit_is_fail_open_when_store_down() -> None:
    class BrokenStore:
        async def eval(self, *args: object, **kwargs: object) -> int:
            raise RedisError("connection refused")

    assert await check_rate_limit(BrokenStore(), "ratelimit:test:broken", 3, 60) is None
