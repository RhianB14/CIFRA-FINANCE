from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.storage import ObjectStorage


class _BucketMissingError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _ClientCtx:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *args: Any) -> None:
        return None


class _SessionStub:
    def __init__(self, client: Any) -> None:
        self._client = client

    def client(self, *args: Any, **kwargs: Any) -> _ClientCtx:
        return _ClientCtx(self._client)


def _client_stub() -> Any:
    client = AsyncMock()
    client.exceptions = type("exceptions", (), {"ClientError": _BucketMissingError})
    return client


def _storage(client: Any) -> ObjectStorage:
    return ObjectStorage(session_factory=lambda: _SessionStub(client))


async def test_ensure_bucket_is_idempotent_when_bucket_exists() -> None:
    client = _client_stub()
    client.head_bucket = AsyncMock(return_value={})

    storage = _storage(client)
    await storage.ensure_bucket()

    client.head_bucket.assert_awaited_once_with(Bucket="cifra-attachments")
    client.create_bucket.assert_not_awaited()


async def test_ensure_bucket_creates_when_missing_404() -> None:
    client = _client_stub()
    client.head_bucket = AsyncMock(side_effect=_BucketMissingError("404"))
    client.create_bucket = AsyncMock(return_value={})

    storage = _storage(client)
    await storage.ensure_bucket()

    client.head_bucket.assert_awaited_once()
    client.create_bucket.assert_awaited_once_with(Bucket="cifra-attachments")


async def test_ensure_bucket_creates_when_missing_no_such_bucket() -> None:
    client = _client_stub()
    client.head_bucket = AsyncMock(side_effect=_BucketMissingError("NoSuchBucket"))
    client.create_bucket = AsyncMock(return_value={})

    storage = _storage(client)
    await storage.ensure_bucket()

    client.create_bucket.assert_awaited_once_with(Bucket="cifra-attachments")


async def test_ensure_bucket_fails_closed_when_create_errors() -> None:
    client = _client_stub()
    client.head_bucket = AsyncMock(side_effect=_BucketMissingError("404"))
    client.create_bucket = AsyncMock(side_effect=ValueError("boom"))

    storage = _storage(client)
    with pytest.raises(ValueError):
        await storage.ensure_bucket()


async def test_ensure_bucket_fails_closed_when_other_error() -> None:
    client = _client_stub()
    client.head_bucket = AsyncMock(side_effect=_BucketMissingError("AccessDenied"))

    storage = _storage(client)
    with pytest.raises(_BucketMissingError):
        await storage.ensure_bucket()
