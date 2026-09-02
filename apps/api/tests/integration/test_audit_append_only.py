from datetime import UTC, datetime

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_bypass_scope
from app.models import AuditEvent
from app.services.audit import AuditEventType, record_audit_event


async def _event_count(db_session: AsyncSession) -> int:
    await set_bypass_scope(db_session)
    result = await db_session.execute(text("SELECT count(*) FROM audit_events"))
    return int(result.scalar_one())


async def test_direct_update_is_rejected_by_database(
    db_session: AsyncSession,
) -> None:
    from app.core.db import set_bypass_scope
    from app.models import User

    await set_bypass_scope(db_session)
    user = User(email="audit-upd@example.com", name="Ana", password_hash="argon2id$x")
    db_session.add(user)
    await db_session.flush()
    await record_audit_event(
        db_session,
        event_type=AuditEventType.LOGIN_SUCCEEDED,
        user_id=user.id,
    )
    await db_session.commit()
    await set_bypass_scope(db_session)
    with pytest.raises(Exception) as error:
        await db_session.execute(
            update(AuditEvent).where(AuditEvent.user_id == user.id).values(actor_ip="0.0.0.0")
        )
        await db_session.commit()
    await db_session.rollback()
    assert "audit_events" in str(error.value)
    assert await _event_count(db_session) == 1


async def test_direct_delete_is_rejected_by_database(
    db_session: AsyncSession,
) -> None:
    from app.core.db import set_bypass_scope
    from app.models import User

    await set_bypass_scope(db_session)
    user = User(email="audit-del@example.com", name="Ana", password_hash="argon2id$x")
    db_session.add(user)
    await db_session.flush()
    await record_audit_event(
        db_session,
        event_type=AuditEventType.LOGIN_SUCCEEDED,
        user_id=user.id,
    )
    await db_session.commit()
    await set_bypass_scope(db_session)
    with pytest.raises(Exception) as error:
        await db_session.execute(
            text("DELETE FROM audit_events WHERE user_id = :id"), {"id": user.id}
        )
        await db_session.commit()
    await db_session.rollback()
    assert "audit_events" in str(error.value)
    assert await _event_count(db_session) == 1


async def test_event_and_use_case_share_transaction_semantics(
    db_session: AsyncSession,
) -> None:
    from app.core.db import set_bypass_scope
    from app.models import User

    await set_bypass_scope(db_session)
    user = User(email="audit-tx@example.com", name="Ana", password_hash="argon2id$x")
    db_session.add(user)
    await db_session.flush()
    await record_audit_event(
        db_session,
        event_type=AuditEventType.TWO_FACTOR_ACTIVATED,
        user_id=user.id,
    )
    await db_session.commit()
    assert await _event_count(db_session) == 1
    occurred = await db_session.execute(
        text("SELECT occurred_at FROM audit_events ORDER BY occurred_at LIMIT 1")
    )
    stamp = occurred.scalar_one()
    assert stamp is not None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(UTC).replace(tzinfo=None)
    now = datetime.now(UTC).replace(tzinfo=None)
    assert abs((now - stamp).total_seconds()) < 60


async def test_multiple_events_batched(db_session: AsyncSession) -> None:
    await set_bypass_scope(db_session)
    for _ in range(3):
        await record_audit_event(
            db_session,
            event_type=AuditEventType.LOGIN_FAILED,
            actor_ip="10.0.0.1",
        )
    assert await _event_count(db_session) == 3
    rows = await db_session.execute(text("SELECT event_type FROM audit_events"))
    assert all(row[0] == "login.failed" for row in rows)
