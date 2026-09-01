from typing import Any

from app.core.settings import Settings


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"rate limit exceeded, retry after {retry_after}s")


def client_ip(peer: str | None, forwarded: str | None, settings: Settings) -> str:
    raise NotImplementedError


async def check_rate_limit(
    store: Any,
    key: str,
    limit: int,
    window_seconds: int,
) -> int | None:
    raise NotImplementedError
