import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent

SECRET_KEY_MARKERS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "token",
        "secret",
        "code",
        "hash",
        "authorization",
        "cookie",
        "credential",
        "apikey",
        "api_key",
    }
)

REDACTED = "[REDACTED]"


class AuditEventType(StrEnum):
    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    LOGIN_LOCKED = "login.locked"
    LOGOUT_PERFORMED = "logout.performed"
    REFRESH_REUSE_DETECTED = "refresh.reuse_detected"
    TWO_FACTOR_ACTIVATED = "two_factor.activated"
    TWO_FACTOR_DEACTIVATED = "two_factor.deactivated"
    TWO_FACTOR_CHALLENGE_FAILED = "two_factor.challenge_failed"
    BACKUP_CODE_USED = "backup_code.used"
    PASSWORD_RESET_REQUESTED = "password_reset.requested"
    PASSWORD_RESET_COMPLETED = "password_reset.completed"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SECRET_KEY_MARKERS)


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if _is_sensitive_key(str(key)) else sanitize_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


async def record_audit_event(
    session: AsyncSession,
    event_type: AuditEventType,
    user_id: uuid.UUID | None = None,
    actor_ip: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            user_id=user_id,
            event_type=str(event_type.value),
            actor_ip=actor_ip,
            entity_type=entity_type,
            entity_id=entity_id,
            before=sanitize_payload(dict(before)) if before is not None else None,
            after=sanitize_payload(dict(after)) if after is not None else None,
        )
    )
    await session.flush()
