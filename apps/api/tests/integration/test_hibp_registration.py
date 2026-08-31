import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.auth as auth_module
from app.services.auth import AuthenticationError

Transport = Callable[[str, dict[str, str], float], Awaitable[str]]
register_user = cast(Any, vars(auth_module)["register_user"])


async def test_hibp_enabled_sends_only_sha1_prefix_and_rejects_compromised(
    db_session: AsyncSession,
) -> None:
    phrase = "Compromised-Password-123"
    full_hash = hashlib.sha1(phrase.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix = full_hash[:5]
    suffix = full_hash[5:]
    calls: list[tuple[str, dict[str, str], float]] = []

    async def transport(path: str, headers: dict[str, str], limit: float) -> str:
        calls.append((path, headers, limit))
        return f"{suffix}:42\nOTHER:1"

    with pytest.raises(AuthenticationError):
        await register_user(
            db_session,
            "hibp@example.com",
            phrase,
            "Ana",
            hibp_enabled=True,
            hibp_transport=transport,
        )
    assert calls == [(f"/range/{prefix}", {"Add-Padding": "true"}, 0.5)]
    flattened = repr(calls)
    assert phrase not in flattened
    assert full_hash not in flattened


async def test_hibp_disabled_never_calls_transport(db_session: AsyncSession) -> None:
    calls = 0

    async def transport(path: str, headers: dict[str, str], limit: float) -> str:
        nonlocal calls
        calls += 1
        return ""

    await register_user(
        db_session,
        "off@example.com",
        "Safe-Password-1234",
        "Ana",
        hibp_enabled=False,
        hibp_transport=transport,
    )
    assert calls == 0
