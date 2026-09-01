import time
import uuid
from typing import Any, cast

import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.two_factor as two_factor_module
from app.core.crypto import decrypt_secret
from app.core.passwords import hash_password
from app.models import BackupCode, RefreshToken, User
from app.services.auth import start_session
from app.services.two_factor import TwoFactorError, confirm_totp, setup_totp

PASSWORD = "Tr0ub4dor&3-Correct-Horse"
disable_totp = cast(Any, vars(two_factor_module)["disable_totp"])


async def enabled_user(session: AsyncSession) -> tuple[User, list[str]]:
    user = User(
        email=f"disable-{uuid.uuid4().hex}@example.com",
        name="Ana",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.commit()
    await setup_totp(session, user)
    seed = decrypt_secret(assert_value(user.totp_pending_secret_encrypted))
    code = pyotp.TOTP(seed).at(int(time.time()))
    codes = await confirm_totp(session, user, code)
    await session.commit()
    return user, codes


def assert_value(value: str | None) -> str:
    assert value is not None
    return value


async def current_totp(user: User) -> str:
    seed = decrypt_secret(assert_value(user.totp_secret_encrypted))
    step = int(time.time() // 30) + 1
    return pyotp.TOTP(seed).at(step * 30)


@pytest.mark.asyncio
async def test_disable_rejects_wrong_password_without_partial_state(
    db_session: AsyncSession,
) -> None:
    user, _ = await enabled_user(db_session)
    factor = await current_totp(user)
    with pytest.raises(TwoFactorError):
        await disable_totp(db_session, user, "wrong-password", factor)
    await db_session.refresh(user)
    assert user.totp_enabled is True
    assert user.session_version == 2
    assert user.totp_secret_encrypted is not None


@pytest.mark.asyncio
async def test_disable_rejects_wrong_factor_without_partial_state(
    db_session: AsyncSession,
) -> None:
    user, _ = await enabled_user(db_session)
    with pytest.raises(TwoFactorError):
        await disable_totp(db_session, user, PASSWORD, "000000")
    await db_session.refresh(user)
    assert user.totp_enabled is True
    assert user.session_version == 2


@pytest.mark.asyncio
async def test_disable_accepts_password_and_backup_code_then_invalidates_sessions(
    db_session: AsyncSession,
) -> None:
    user, codes = await enabled_user(db_session)
    _, refresh = await start_session(db_session, user)
    await disable_totp(db_session, user, PASSWORD, codes[0])
    await db_session.commit()
    await db_session.refresh(user)
    assert user.totp_enabled is False
    assert user.session_version == 3
    assert user.totp_secret_encrypted is None
    assert user.totp_pending_secret_encrypted is None
    result = await db_session.execute(select(BackupCode).where(BackupCode.user_id == user.id))
    assert list(result.scalars()) == []
    tokens = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    rows = list(tokens.scalars())
    assert rows
    assert all(row.revoked_at is not None for row in rows)
    assert refresh


@pytest.mark.asyncio
async def test_disable_rolls_back_every_change_when_commit_fails(
    db_session: AsyncSession,
) -> None:
    user, codes = await enabled_user(db_session)
    user_id = user.id
    await disable_totp(db_session, user, PASSWORD, codes[0])
    await db_session.rollback()
    current = await db_session.get(User, user_id)
    assert current is not None
    assert current.totp_enabled is True
    assert current.session_version == 2
    result = await db_session.execute(select(BackupCode).where(BackupCode.user_id == user_id))
    assert len(list(result.scalars())) == 10
