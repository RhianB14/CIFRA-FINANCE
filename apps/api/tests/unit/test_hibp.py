from typing import Any

import pytest

from app.core.hibp import HIBPClient, HIBPUnavailableError
from app.core.settings import Settings


class FakeTransport:
    def __init__(self, response: str, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.requests: list[tuple[str, dict[str, str], float]] = []

    async def __call__(
        self,
        path: str,
        headers: dict[str, str],
        limit: float,
    ) -> str:
        self.requests.append((path, headers, limit))
        if self.fail:
            message = "network error"
            raise RuntimeError(message)
        return self.response


def make_client(transport: FakeTransport, **kwargs: Any) -> HIBPClient:
    return HIBPClient(transport=transport, timeout_seconds=0.5, **kwargs)


async def test_disabled_by_default() -> None:
    assert Settings().hibp_enabled is False


async def test_enabled_check_returns_true_on_breach_match() -> None:
    phrase = "Compromised-Password-123"
    transport = FakeTransport("E7D168DBB7972B6DF648CE80828015C4772:23\n")
    client = make_client(transport)
    assert await client.check_password(phrase) is True


async def test_enabled_check_returns_false_on_absent_suffix() -> None:
    transport = FakeTransport("ABCDEF:23\n")
    client = make_client(transport)
    assert await client.check_password("Safe-Password-1234") is False


async def test_transport_receives_only_prefix() -> None:
    transport = FakeTransport("")
    client = make_client(transport)
    await client.check_password("Safe-Password-1234")
    assert len(transport.requests) == 1
    path, headers, limit = transport.requests[0]
    assert path.startswith("/range/")
    assert len(path.rsplit("/", 1)[1]) == 5
    assert headers == {"Add-Padding": "true"}
    assert limit == 0.5


async def test_policy_fail_open_option() -> None:
    transport = FakeTransport("", fail=True)
    client = make_client(transport, fail_closed=False)
    assert await client.check_password("Safe-Password-1234") is False


async def test_policy_fail_closed_by_default() -> None:
    transport = FakeTransport("", fail=True)
    client = make_client(transport)
    with pytest.raises(HIBPUnavailableError):
        await client.check_password("Safe-Password-1234")


async def test_timeout_is_injected() -> None:
    transport = FakeTransport("")
    client = make_client(transport)
    assert client.timeout_seconds == 0.5
