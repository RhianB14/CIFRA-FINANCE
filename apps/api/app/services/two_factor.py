import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.totp import (
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    provisioning_uri,
    verify_totp,
)
from app.models import BackupCode, User


class TwoFactorError(Exception):
    pass


class TwoFactorNotEnabledError(TwoFactorError):
    pass


class TwoFactorAlreadyEnabledError(TwoFactorError):
    pass


def _is_backup_code(code: str) -> bool:
    normalized = code.strip().upper()
    return len(normalized) == 9 and normalized[4] == "-"


async def _consume_backup_code(session: AsyncSession, user: User, code: str) -> bool:
    code_hash = hash_backup_code(code)
    result = await session.execute(
        update(BackupCode)
        .where(
            BackupCode.user_id == user.id,
            BackupCode.code_hash == code_hash,
            BackupCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
        .returning(BackupCode.id)
        .execution_options(synchronize_session=False)
    )
    consumed = result.scalar_one_or_none()
    await session.commit()
    return consumed is not None


async def setup_totp(session: AsyncSession, user: User) -> str:
    if user.totp_enabled:
        raise TwoFactorAlreadyEnabledError("two factor is already enabled")
    seed = generate_totp_secret()
    user.totp_pending_secret_encrypted = encrypt_secret(seed)
    await session.commit()
    return provisioning_uri(user.email, seed)


async def confirm_totp(session: AsyncSession, user: User, code: str) -> list[str]:
    if user.totp_enabled:
        raise TwoFactorAlreadyEnabledError("two factor is already enabled")
    if not user.totp_pending_secret_encrypted:
        raise TwoFactorError("no pending two factor enrollment")
    seed = decrypt_secret(user.totp_pending_secret_encrypted)
    accepted, step = verify_totp(seed, code, last_step=user.totp_last_step)
    if not accepted or step is None:
        raise TwoFactorError("invalid confirmation code")
    codes = generate_backup_codes()
    for value in codes:
        session.add(BackupCode(user_id=user.id, code_hash=hash_backup_code(value)))
    user.totp_secret_encrypted = user.totp_pending_secret_encrypted
    user.totp_pending_secret_encrypted = None
    user.totp_enabled = True
    user.totp_last_step = None
    user.totp_confirmed_at = datetime.now(UTC)
    await session.commit()
    return codes


async def verify_second_factor(session: AsyncSession, user: User, code: str) -> None:
    if not user.totp_enabled:
        raise TwoFactorNotEnabledError("two factor is not enabled")
    sealed = user.totp_secret_encrypted
    if sealed is None:
        raise TwoFactorNotEnabledError("two factor secret is missing")
    if _is_backup_code(code):
        if await _consume_backup_code(session, user, code):
            return
        raise TwoFactorError("backup code is invalid or already used")
    seed = decrypt_secret(sealed)
    accepted, step = verify_totp(seed, code, last_step=user.totp_last_step)
    if not accepted or step is None:
        raise TwoFactorError("invalid second factor code")
    user.totp_last_step = step
    await session.commit()


async def disable_totp(session: AsyncSession, user: User, code: str) -> None:
    if not user.totp_enabled:
        raise TwoFactorNotEnabledError("two factor is not enabled")
    await verify_second_factor(session, user, code)
    await session.execute(delete(BackupCode).where(BackupCode.user_id == user_id_value(user)))
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_pending_secret_encrypted = None
    user.totp_last_step = None
    user.totp_confirmed_at = None
    await session.commit()


def user_id_value(user: User) -> uuid.UUID:
    return user.id
