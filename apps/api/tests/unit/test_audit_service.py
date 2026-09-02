import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, User
from app.services.audit import (
    SECRET_KEY_MARKERS,
    AuditEventType,
    record_audit_event,
)


async def _make_user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email, name="Ana", password_hash="argon2id$x")
    db_session.add(user)
    await db_session.flush()
    return user


def test_audit_event_type_values_are_stable() -> None:
    assert AuditEventType.LOGIN_SUCCEEDED.value == "login.succeeded"
    assert AuditEventType.LOGIN_FAILED.value == "login.failed"
    assert AuditEventType.LOGIN_LOCKED.value == "login.locked"
    assert AuditEventType.LOGOUT_PERFORMED.value == "logout.performed"
    assert AuditEventType.REFRESH_REUSE_DETECTED.value == "refresh.reuse_detected"
    assert AuditEventType.TWO_FACTOR_ACTIVATED.value == "two_factor.activated"
    assert AuditEventType.TWO_FACTOR_DEACTIVATED.value == "two_factor.deactivated"
    assert AuditEventType.TWO_FACTOR_CHALLENGE_FAILED.value == ("two_factor.challenge_failed")
    assert AuditEventType.BACKUP_CODE_USED.value == "backup_code.used"
    assert AuditEventType.PASSWORD_RESET_REQUESTED.value == "password_reset.requested"
    assert AuditEventType.PASSWORD_RESET_COMPLETED.value == "password_reset.completed"


def test_secret_key_markers_are_explicit() -> None:
    for marker in SECRET_KEY_MARKERS:
        assert isinstance(marker, str)
    for required in ("password", "token", "secret", "code", "hash", "authorization"):
        assert required in SECRET_KEY_MARKERS


async def test_record_audit_event_persists_minimal_fields(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "audit-min@example.com")
    await record_audit_event(
        db_session,
        event_type=AuditEventType.LOGIN_SUCCEEDED,
        user_id=user.id,
        actor_ip="203.0.113.7",
    )
    result = await db_session.execute(select(AuditEvent))
    stored = result.scalar_one()
    assert stored.event_type == "login.succeeded"
    assert stored.user_id == user.id
    assert stored.actor_ip == "203.0.113.7"
    assert stored.before is None
    assert stored.after is None


async def test_record_audit_event_sanitizes_sensitive_payload_keys(
    db_session: AsyncSession,
) -> None:
    await record_audit_event(
        db_session,
        event_type=AuditEventType.TWO_FACTOR_ACTIVATED,
        entity_type="user",
        before={"totp_enabled": False},
        after={
            "totp_enabled": True,
            "totp_secret": "JBSWY3DPEHPK3PXP",
            "backup_codes": ["1111-2222", "3333-4444"],
            "nested": {"refresh_token": "jwt-value"},
            "items": [{"password": "plain"}],
        },
    )
    result = await db_session.execute(select(AuditEvent))
    stored = result.scalar_one()
    assert stored.before == {"totp_enabled": False}
    assert stored.after is not None
    assert stored.after["totp_enabled"] is True
    assert stored.after["totp_secret"] == "[REDACTED]"
    assert stored.after["backup_codes"] == "[REDACTED]"
    assert stored.after["nested"] == {"refresh_token": "[REDACTED]"}
    assert stored.after["items"] == [{"password": "[REDACTED]"}]
    rendered = repr(stored.after)
    assert "JBSWY3DPEHPK3PXP" not in rendered
    assert "1111-2222" not in rendered
    assert "jwt-value" not in rendered
    assert "plain" not in rendered


async def test_record_audit_event_preserves_descriptive_keys(
    db_session: AsyncSession,
) -> None:
    entity = uuid.uuid4()
    await record_audit_event(
        db_session,
        event_type=AuditEventType.REFRESH_REUSE_DETECTED,
        entity_type="refresh_token",
        entity_id=entity,
        after={"family_id": "f", "reason": "reuse"},
    )
    result = await db_session.execute(select(AuditEvent))
    stored = result.scalar_one()
    assert stored.entity_id == entity
    assert stored.after == {"family_id": "f", "reason": "reuse"}


async def test_record_audit_event_accepts_missing_user(db_session: AsyncSession) -> None:
    await record_audit_event(
        db_session,
        event_type=AuditEventType.LOGIN_FAILED,
        actor_ip="192.0.2.9",
        after={"email_domain": "example.com"},
    )
    result = await db_session.execute(select(AuditEvent))
    stored = result.scalar_one()
    assert stored.user_id is None
    assert stored.after == {"email_domain": "example.com"}


@pytest.mark.parametrize(
    "raw",
    [
        3,
        [1, 2],
        {"ok": True},
        None,
    ],
)
async def test_record_audit_event_handles_non_string_payloads(
    db_session: AsyncSession,
    raw: object,
) -> None:
    await record_audit_event(
        db_session,
        event_type=AuditEventType.LOGIN_FAILED,
        after={"count": raw, "detail": "text"},
    )
    result = await db_session.execute(select(AuditEvent))
    stored = result.scalar_one()
    assert stored.after == {"count": raw, "detail": "text"}
