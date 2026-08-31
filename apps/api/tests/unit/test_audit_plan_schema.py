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
    event = AuditEvent(
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
    assert reloaded.entity_type == "user"
    assert reloaded.entity_id == user.id
    assert reloaded.before == before
    assert reloaded.after == after
    assert reloaded.actor_ip == "127.0.0.1"
    assert reloaded.occurred_at is not None


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
    assert reloaded.is_active is True

    reloaded.is_active = False
    await db_session.commit()

    persisted = (
        await db_session.execute(select(User).where(User.email == "audit.active@example.com"))
    ).scalar_one()
    assert persisted.is_active is False
