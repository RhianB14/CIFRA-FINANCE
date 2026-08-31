import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.core.tokens import create_refresh_token, decode_refresh_token
from app.models import RefreshToken
from app.services.session_revocation import (
    bump_session_version,
    publish_session_version,
)

RedisLike = redis.Redis

JTI_HASH_LENGTH = 64


class RotationError(Exception):
    pass


class TokenNotFoundError(RotationError):
    pass


class TokenExpiredError(RotationError):
    pass


class ReuseDetectedError(RotationError):
    pass


def hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def _default_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


async def issue_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    family_id: uuid.UUID | None = None,
    device_label: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, RefreshToken]:
    resolved_family = family_id or uuid.uuid4()
    signed = create_refresh_token(user_id, resolved_family)
    payload = decode_refresh_token(signed)
    row = RefreshToken(
        user_id=user_id,
        jti_hash=hash_jti(str(payload["jti"])),
        family_id=resolved_family,
        device_label=device_label,
        expires_at=expires_at
        or datetime.now(UTC) + timedelta(days=get_settings().refresh_token_ttl_days),
    )
    session.add(row)
    await session.flush()
    return signed, row


async def _load_token(session: AsyncSession, jti_hash: str) -> RefreshToken:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.jti_hash == jti_hash).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise TokenNotFoundError("refresh token not recognized")
    return row


def _ensure_rotatable(row: RefreshToken) -> None:
    if row.expires_at <= datetime.now(UTC):
        raise TokenExpiredError("refresh token expired")
    if row.revoked_at is not None:
        raise ReuseDetectedError("refresh token already used")


async def revoke_all_refresh_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for row in result.scalars():
        row.revoked_at = datetime.now(UTC)


async def rotate_refresh_token(
    session: AsyncSession,
    refresh_token: str,
    redis_client: RedisLike | None = None,
) -> tuple[str, RefreshToken]:
    payload = decode_refresh_token(refresh_token)
    jti_hash = hash_jti(str(payload["jti"]))
    user_id = uuid.UUID(str(payload["sub"]))
    row = await _load_token(session, jti_hash)
    if row.user_id != user_id:
        raise ReuseDetectedError("subject mismatch")
    try:
        _ensure_rotatable(row)
    except ReuseDetectedError:
        await revoke_all_refresh_tokens(session, user_id)
        session_version = await bump_session_version(session, user_id)
        await session.commit()
        await publish_session_version(user_id, session_version, client=redis_client)
        raise
    family_id = row.family_id
    new_jwt, new_row = await issue_refresh_token(
        session,
        user_id,
        family_id=family_id,
        device_label=row.device_label,
    )
    row.revoked_at = datetime.now(UTC)
    row.replaced_by = new_row.id
    await session.commit()
    return new_jwt, new_row


async def revoke_session(
    session: AsyncSession,
    refresh_token: str,
    redis_client: RedisLike | None = None,
) -> None:
    payload = decode_refresh_token(refresh_token)
    jti_hash = hash_jti(str(payload["jti"]))
    row = await _load_token(session, jti_hash)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.commit()
