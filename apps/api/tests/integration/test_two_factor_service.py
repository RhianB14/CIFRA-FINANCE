import time
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret
from app.core.db import bind_current_user
from app.core.passwords import hash_password
from app.models import BackupCode, User
from app.services.two_factor import (
    TwoFactorAlreadyEnabledError,
    TwoFactorError,
    TwoFactorNotEnabledError,
    confirm_totp,
    disable_totp,
    setup_totp,
    verify_second_factor,
)


async def make_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid4().hex}@example.com",
        name="Ana",
        password_hash=hash_password("Tr0ub4dor&3-Correct-Horse"),
    )
    session.add(user)
    await session.commit()
    await bind_current_user(session, user.id)
    return user


async def backup_hashes(session: AsyncSession, user: User) -> set[str]:
    result = await session.execute(
        select(BackupCode.code_hash).where(BackupCode.user_id == user.id)
    )
    return {str(row[0]) for row in result}


@pytest.mark.asyncio
async def test_setup_stores_encrypted_pending_secret(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    uri = await setup_totp(db_session, user)
    assert uri.startswith("otpauth://totp/")
    assert user.totp_pending_secret_encrypted is not None
    assert user.totp_pending_secret_encrypted != decrypt_secret(
        assert_value(user.totp_pending_secret_encrypted)
    )
    assert user.totp_enabled is False


@pytest.mark.asyncio
async def test_setup_rejected_when_already_enabled(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await setup_totp(db_session, user)
    seed = decrypt_secret(assert_value(user.totp_pending_secret_encrypted))
    code = pyotp.TOTP(seed).at(int(time.time()))
    await confirm_totp(db_session, user, code)
    with pytest.raises(TwoFactorAlreadyEnabledError):
        await setup_totp(db_session, user)


@pytest.mark.asyncio
async def test_confirm_with_valid_code_enables_and_creates_backup_codes(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    await setup_totp(db_session, user)
    seed = decrypt_secret(assert_value(user.totp_pending_secret_encrypted))
    code = pyotp.TOTP(seed).at(int(time.time()))
    codes = await confirm_totp(db_session, user, code)
    assert len(codes) == 10
    assert user.totp_enabled is True
    assert user.totp_pending_secret_encrypted is None
    assert user.totp_secret_encrypted is not None
    assert user.totp_confirmed_at is not None
    hashes = await backup_hashes(db_session, user)
    assert len(hashes) == 10
    for stored in hashes:
        assert stored not in codes


@pytest.mark.asyncio
async def test_confirm_with_wrong_code_keeps_pending(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await setup_totp(db_session, user)
    with pytest.raises(TwoFactorError):
        await confirm_totp(db_session, user, "000000")
    assert user.totp_enabled is False
    assert user.totp_pending_secret_encrypted is not None
    assert await backup_hashes(db_session, user) == set()


@pytest.mark.asyncio
async def test_confirm_without_enrollment_rejected(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(TwoFactorError):
        await confirm_totp(db_session, user, "123456")


@pytest.mark.asyncio
async def test_second_factor_totp_accepted_and_step_recorded(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    await enroll(db_session, user)
    user.totp_last_step = None
    await db_session.commit()
    code = pyotp.TOTP(decrypt_secret(assert_value(user.totp_secret_encrypted))).at(int(time.time()))
    await verify_second_factor(db_session, user, code)
    assert user.totp_last_step is not None


@pytest.mark.asyncio
async def test_second_factor_rejects_replayed_step(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await enroll(db_session, user)
    current_step = int(time.time() // 30)
    user.totp_last_step = current_step
    await db_session.commit()
    code = pyotp.TOTP(decrypt_secret(assert_value(user.totp_secret_encrypted))).at(
        current_step * 30
    )
    with pytest.raises(TwoFactorError):
        await verify_second_factor(db_session, user, code)


@pytest.mark.asyncio
async def test_second_factor_rejects_before_enablement(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(TwoFactorNotEnabledError):
        await verify_second_factor(db_session, user, "123456")


@pytest.mark.asyncio
async def test_backup_code_authenticates_once(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    codes = await enroll(db_session, user)
    await verify_second_factor(db_session, user, codes[0])
    hashes = await backup_hashes(db_session, user)
    assert len(hashes) == 10
    result = await db_session.execute(
        select(BackupCode).where(BackupCode.user_id == user.id, BackupCode.used_at.isnot(None))
    )
    consumed = list(result.scalars())
    assert len(consumed) == 1
    with pytest.raises(TwoFactorError):
        await verify_second_factor(db_session, user, codes[0])


@pytest.mark.asyncio
async def test_unknown_backup_code_rejected(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await enroll(db_session, user)
    with pytest.raises(TwoFactorError):
        await verify_second_factor(db_session, user, "ZZZZ-ZZZZ")


@pytest.mark.asyncio
async def test_disable_with_totp_code_wipes_state(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await enroll(db_session, user)
    user.totp_last_step = None
    await db_session.commit()
    code = pyotp.TOTP(decrypt_secret(assert_value(user.totp_secret_encrypted))).at(int(time.time()))
    await disable_totp(db_session, user, "Tr0ub4dor&3-Correct-Horse", code)
    assert user.totp_enabled is False
    assert user.totp_secret_encrypted is None
    assert user.totp_pending_secret_encrypted is None
    assert user.totp_last_step is None
    assert user.totp_confirmed_at is None
    assert await backup_hashes(db_session, user) == set()


@pytest.mark.asyncio
async def test_disable_with_backup_code_wipes_state(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    codes = await enroll(db_session, user)
    await disable_totp(db_session, user, "Tr0ub4dor&3-Correct-Horse", codes[1])
    assert user.totp_enabled is False


@pytest.mark.asyncio
async def test_disable_with_wrong_code_keeps_enabled(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await enroll(db_session, user)
    with pytest.raises(TwoFactorError):
        await disable_totp(db_session, user, "Tr0ub4dor&3-Correct-Horse", "000000")
    assert user.totp_enabled is True


async def enroll(session: AsyncSession, user: User) -> list[str]:
    await setup_totp(session, user)
    seed = decrypt_secret(assert_value(user.totp_pending_secret_encrypted))
    code = pyotp.TOTP(seed).at(int(time.time()))
    return await confirm_totp(session, user, code)


def assert_value(value: str | None) -> str:
    assert value is not None
    return value
