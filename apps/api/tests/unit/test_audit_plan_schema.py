from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, User


async def test_audit_event_matches_master_plan_schema(db_session: AsyncSession) -> None:
    user = User(
        email="audit.plan@example.com",
        name="Audit Plan",
        password_hash="x" * 255,
    )
    db_session.add(user)
    await db_session.commit()

    before = {"key": "old-value"}
    after = {"key": "new-value"}
    flexible_audit_event = cast(Any, AuditEvent)
    event = flexible_audit_event(
        user_id=user.id,
        event_type="auth.login",
        actor_ip="127.0.0.1",
        entity_type="user",
        entity_id=user.id,
        before=before,
        after=after,
    )
    db_session.add(event)
    await db_session.commit()

    reloaded = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.user_id == user.id))
    ).scalar_one()
    readable = cast(Any, reloaded)
    assert readable.entity_type == "user"
    assert readable.entity_id == user.id
    assert readable.before == before
    assert readable.after == after
    assert readable.actor_ip == "127.0.0.1"
    assert readable.occurred_at is not None


async def test_user_defaults_to_active(db_session: AsyncSession) -> None:
    user = User(
        email="audit.active@example.com",
        name="Active User",
        password_hash="x" * 255,
    )
    db_session.add(user)
    await db_session.commit()

    reloaded = (
        await db_session.execute(select(User).where(User.email == "audit.active@example.com"))
    ).scalar_one()
    assert cast(Any, reloaded).is_active is True

    cast(Any, reloaded).is_active = False
    await db_session.commit()

    persisted = (
        await db_session.execute(select(User).where(User.email == "audit.active@example.com"))
    ).scalar_one()
    assert cast(Any, persisted).is_active is False
