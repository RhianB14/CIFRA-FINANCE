import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import aioboto3
from botocore.config import Config as BotoConfig

from app.core.settings import get_settings


class StorageError(Exception):
    pass


def _default_session_factory() -> Any:
    s = get_settings()
    return aioboto3.Session(
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
    )


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    object_key: str
    bucket: str
    etag: str
    size_bytes: int


class ObjectStorage:
    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        settings = get_settings()
        self._endpoint = settings.s3_endpoint
        self._bucket = settings.s3_bucket_name
        self._region = settings.s3_region
        self._access = settings.s3_access_key
        self._secret_material = settings.s3_secret_key
        self._session_factory = session_factory or _default_session_factory

    async def ensure_bucket(self) -> None:
        session = self._session_factory()
        async with session.client(
            "s3",
            endpoint_url=self._endpoint,
            config=BotoConfig(signature_version="s3v4"),
        ) as client:
            try:
                await client.head_bucket(Bucket=self._bucket)
                return
            except client.exceptions.ClientException:
                await client.create_bucket(Bucket=self._bucket)

    async def put(self, account_id: UUID, file_name: str, content: bytes) -> StoredAttachment:
        object_key = f"accounts/{account_id}/{uuid.uuid4().hex}-{file_name}"
        session = aioboto3.Session(
            aws_access_key_id=self._access,
            aws_secret_access_key=self._secret_material,
            region_name=self._region,
        )
        async with session.client(
            "s3",
            endpoint_url=self._endpoint,
            config=BotoConfig(signature_version="s3v4"),
        ) as client:
            response = await client.put_object(Bucket=self._bucket, Key=object_key, Body=content)
            etag = str(response["ETag"]).strip('"')
        return StoredAttachment(
            object_key=object_key,
            bucket=self._bucket,
            etag=etag,
            size_bytes=len(content),
        )

    async def get(self, object_key: str, bucket: str) -> bytes:
        session = aioboto3.Session(
            aws_access_key_id=self._access,
            aws_secret_access_key=self._secret_material,
            region_name=self._region,
        )
        async with session.client(
            "s3",
            endpoint_url=self._endpoint,
            config=BotoConfig(signature_version="s3v4"),
        ) as client:
            response = await client.get_object(Bucket=bucket, Key=object_key)
            body: bytes = await response["Body"].read()
            return body
