from typing import Protocol

from app.core.settings import get_settings


class HIBPTransport(Protocol):
    async def __call__(self, suffix: str) -> str: ...


class HIBPClient:
    def __init__(
        self,
        transport: HIBPTransport,
        timeout_seconds: float | None = None,
        fail_closed: bool = False,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else get_settings().hibp_timeout_seconds
        )
        self.fail_closed = fail_closed

    async def check_breached(self, suffix: str) -> bool:
        try:
            body = await self.transport(suffix)
        except Exception:
            if self.fail_closed:
                raise
            return False
        for line in body.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0].upper() == suffix.upper():
                return True
        return False
