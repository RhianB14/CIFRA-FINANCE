import pytest

from app.core.emails import normalize_email
from app.core.passwords import (
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password,
)
from app.core.settings import get_settings


@pytest.mark.parametrize(
    "password",
    [
        "curta12",
        "a" * 11,
    ],
)
def test_rejects_passwords_below_minimum(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        "senha-segura-123",
        "a" * 12,
        "a" * 128,
    ],
)
def test_accepts_passwords_within_bounds(password: str) -> None:
    validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        "a" * 129,
        "a" * 5000,
    ],
)
def test_rejects_passwords_above_maximum(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


def test_policy_error_does_not_echo_password() -> None:
    password = "a" * 11
    with pytest.raises(PasswordPolicyError) as raised:
        validate_password(password)
    assert password not in str(raised.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Ana.Silva@Example.COM  ", "ana.silva@example.com"),
        ("ANA@EXAMPLE.COM", "ana@example.com"),
        ("ana@EXAMPLE.com", "ana@example.com"),
    ],
)
def test_normalize_email_is_deterministic(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected
    assert normalize_email(normalize_email(raw)) == normalize_email(raw)


def test_needs_rehash_detects_weaker_parameters() -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, hash_len=16, salt_len=8)
    weak_hash = weak.hash("senha-segura-123")
    assert needs_rehash(weak_hash) is True


def test_needs_rehash_false_for_current_parameters() -> None:
    current = hash_password("senha-segura-123")
    assert needs_rehash(current) is False


def test_validate_password_uses_configured_bounds() -> None:
    settings = get_settings()
    assert settings.password_min_length == 12
    assert settings.password_max_length == 128
