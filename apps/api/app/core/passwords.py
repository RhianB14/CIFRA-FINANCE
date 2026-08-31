from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.settings import get_settings

_hasher: PasswordHasher | None = None


def get_hasher() -> PasswordHasher:
    global _hasher
    if _hasher is None:
        settings = get_settings()
        _hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
            hash_len=settings.argon2_hash_length,
            salt_len=16,
        )
    return _hasher


def reset_hasher() -> None:
    global _hasher
    _hasher = None


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    settings = get_settings()
    if len(password) < settings.password_min_length:
        message = "password does not meet the minimum length requirement"
        raise PasswordPolicyError(message)
    if len(password) > settings.password_max_length:
        message = "password exceeds the maximum allowed length"
        raise PasswordPolicyError(message)


def hash_password(password: str) -> str:
    return get_hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        get_hasher().verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return get_hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return False
