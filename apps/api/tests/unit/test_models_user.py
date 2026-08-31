from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password
from app.models import AuditEvent, BackupCode, RefreshToken, User


def make_user(email: str = "ana.silva@example.com") -> User:
    return User(email=email, name="Ana", password_hash=hash_password("senha-segura-123"))


async def test_creates_user_with_defaults(db_session: AsyncSession) -> None:
    user = make_user("Ana.Silva@Example.COM")
    db_session.add(user)
    await db_session.commit()

    stored = await db_session.get(User, user.id)
    assert stored is not None
    assert stored.email == "ana.silva@example.com"
    assert stored.created_at.tzinfo is not None
    assert stored.updated_at.tzinfo is not None
    assert stored.totp_enabled is False
    assert stored.totp_last_step is None


async def test_user_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(make_user())
    await db_session.commit()

    db_session.add(make_user())
    try:
        await db_session.commit()
        raised = False
    except Exception:
        await db_session.rollback()
        raised = True
    assert raised


async def test_refresh_token_rotation_state(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    token = RefreshToken(
        user_id=user.id,
        jti_hash="a" * 64,
        family_id="f" * 32,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db_session.add(token)
    await db_session.commit()

    stored = await db_session.get(RefreshToken, token.id)
    assert stored is not None
    assert stored.revoked_at is None
    assert stored.replaced_by is None


async def test_backup_code_single_use(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    code = BackupCode(user_id=user.id, code_hash="b" * 64)
    db_session.add(code)
    await db_session.commit()

    stored = await db_session.get(BackupCode, code.id)
    assert stored is not None
    assert stored.used_at is None

    stored.used_at = datetime.now(UTC)
    await db_session.commit()
    query = select(BackupCode).where(BackupCode.id == code.id)
    reloaded = (await db_session.execute(query)).scalar_one()
    assert reloaded.used_at is not None


async def test_audit_event_defaults(db_session: AsyncSession) -> None:
    user = make_user()
    db_session.add(user)
    await db_session.commit()

    event = AuditEvent(user_id=user.id, event_type="auth.login", ip_address="127.0.0.1")
    db_session.add(event)
    await db_session.commit()

    stored = await db_session.get(AuditEvent, event.id)
    assert stored is not None
    assert stored.created_at.tzinfo is not None
