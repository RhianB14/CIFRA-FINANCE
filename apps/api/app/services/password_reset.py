import hashlib
import hmac
import secrets
import uuid
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password
from app.core.settings import get_settings
from app.models import User
from app.services.audit import AuditEventType, record_audit_event
from app.services.rotation import revoke_all_refresh_tokens
from app.services.session_revocation import bump_session_version

RESET_KEY_PREFIX = "cifra:reset:"
RESET_TOKEN_BYTES = 32


class ResetTokenInvalidError(Exception):
    pass


class ResetStoreUnavailableError(Exception):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_key(token: str) -> str:
    return RESET_KEY_PREFIX + _hash_token(token)


async def issue_reset_token(
    store: Any,
    user_id: uuid.UUID,
    session: AsyncSession | None = None,
) -> str:
    if session is not None:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            ghost = secrets.token_urlsafe(RESET_TOKEN_BYTES)
            return ghost
    settings = get_settings()
    issued = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    try:
        await store.set(
            reset_key(issued),
            str(user_id),
            ex=settings.password_reset_ttl_minutes * 60,
        )
    except (redis.RedisError, OSError) as error:
        raise ResetStoreUnavailableError("reset store unavailable") from error
    return issued


async def consume_reset_token(store: Any, token: str) -> uuid.UUID:
    try:
        stored = await store.getdel(reset_key(token))
    except (redis.RedisError, OSError) as error:
        raise ResetStoreUnavailableError("reset store unavailable") from error
    if stored is None:
        raise ResetTokenInvalidError("reset token is invalid or expired")
    try:
        return uuid.UUID(stored)
    except ValueError as error:
        raise ResetTokenInvalidError("reset token is invalid") from error


async def reset_password(
    session: AsyncSession,
    store: Any,
    token: str,
    new_password: str,
) -> None:
    user_id = await consume_reset_token(store, token)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise ResetTokenInvalidError("reset token is invalid or expired")
    user.password_hash = hash_password(new_password)
    await revoke_all_refresh_tokens(session, user.id)
    user.session_version = await bump_session_version(session, user.id)
    await record_audit_event(
        session,
        event_type=AuditEventType.PASSWORD_RESET_COMPLETED,
        user_id=user.id,
        after={"outcome": "password_reset_completed"},
    )
    await session.commit()


def tokens_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
