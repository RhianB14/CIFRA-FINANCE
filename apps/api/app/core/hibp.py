import asyncio
import hashlib
from typing import Protocol

import httpx

from app.core.settings import get_settings


class HIBPTransport(Protocol):
    async def __call__(
        self,
        path: str,
        headers: dict[str, str],
        limit: float,
    ) -> str: ...


async def http_hibp_transport(
    path: str,
    headers: dict[str, str],
    limit: float,
) -> str:
    async with httpx.AsyncClient(
        base_url="https://api.pwnedpasswords.com",
        timeout=limit,
    ) as client:
        response = await client.get(path, headers=headers)
        response.raise_for_status()
        return response.text


class HIBPUnavailableError(Exception):
    pass


class HIBPClient:
    def __init__(
        self,
        transport: HIBPTransport = http_hibp_transport,
        timeout_seconds: float | None = None,
        fail_closed: bool = True,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else get_settings().hibp_timeout_seconds
        )
        self.fail_closed = fail_closed

    async def check_password(self, phrase: str) -> bool:
        digest = hashlib.sha1(phrase.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            async with asyncio.timeout(self.timeout_seconds):
                body = await self.transport(
                    f"/range/{prefix}",
                    {"Add-Padding": "true"},
                    self.timeout_seconds,
                )
        except Exception as error:
            if self.fail_closed:
                raise HIBPUnavailableError("password breach service unavailable") from error
            return False
        for line in body.splitlines():
            parts = line.strip().split(":", 1)
            if len(parts) == 2 and parts[0].upper() == suffix:
                return True
        return False
