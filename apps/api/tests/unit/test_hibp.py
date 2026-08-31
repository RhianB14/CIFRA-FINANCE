from typing import Any

import pytest

from app.core.hibp import HIBPClient
from app.core.settings import Settings


class FakeTransport:
    def __init__(self, response: str, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.requests: list[str] = []

    async def __call__(self, suffix: str) -> str:
        self.requests.append(suffix)
        if self.fail:
            message = "network error"
            raise RuntimeError(message)
        return self.response


def make_client(transport: FakeTransport, **kwargs: Any) -> HIBPClient:
    return HIBPClient(transport=transport, timeout_seconds=0.5, **kwargs)


async def test_disabled_by_default() -> None:
    assert Settings().hibp_enabled is False


async def test_enabled_check_returns_true_on_breach_match() -> None:
    transport = FakeTransport("5PAAH5:1\nABCDEF:23\n")
    client = make_client(transport)
    assert await client.check_breached("5PAAH5") is True


async def test_enabled_check_returns_false_on_absent_suffix() -> None:
    transport = FakeTransport("ABCDEF:23\n")
    client = make_client(transport)
    assert await client.check_breached("5PAAH5") is False


async def test_transport_receives_only_suffix() -> None:
    transport = FakeTransport("")
    client = make_client(transport)
    await client.check_breached("5PAAH5")
    assert transport.requests == ["5PAAH5"]


async def test_policy_fail_open_by_default() -> None:
    transport = FakeTransport("", fail=True)
    client = make_client(transport)
    assert await client.check_breached("5PAAH5") is False


async def test_policy_fail_closed_option() -> None:
    transport = FakeTransport("", fail=True)
    client = make_client(transport, fail_closed=True)
    with pytest.raises(RuntimeError):
        await client.check_breached("5PAAH5")


async def test_timeout_is_injected() -> None:
    transport = FakeTransport("")
    client = make_client(transport)
    assert client.timeout_seconds == 0.5
