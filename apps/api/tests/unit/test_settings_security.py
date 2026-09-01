from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.core.settings import (
    CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS,
    Settings,
    ensure_secure_configuration,
)


def make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "jwt_signing_key": "unit-test-signing-key-0123456789abcdef0123456789abcdef",
        "totp_encryption_key": Fernet.generate_key().decode(),
        "environment": "production",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_accepts_strong_keys_in_production() -> None:
    ensure_secure_configuration(make_settings())


def test_rejects_empty_jwt_signing_key() -> None:
    settings = make_settings(jwt_signing_key="", totp_encryption_key="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "jwt_signing_key" in str(raised.value)


def test_rejects_short_signing_key() -> None:
    settings = make_settings(jwt_signing_key="short-key")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "jwt_signing_key" in str(raised.value)


def test_rejects_missing_totp_encryption_key() -> None:
    settings = make_settings(totp_encryption_key="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_encryption_key" in str(raised.value)


def test_rejects_shared_keys_between_jwt_and_totp() -> None:
    shared = "same-key-0123456789abcdef0123456789abcdef"
    settings = make_settings(jwt_signing_key=shared, totp_encryption_key=shared)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_encryption_key" in str(raised.value)


def test_non_exempt_environment_still_validates_keys() -> None:
    settings = make_settings(environment="testing", jwt_signing_key="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "jwt_signing_key" in str(raised.value)


def test_test_environment_is_exempt() -> None:
    settings = make_settings(jwt_signing_key="", totp_encryption_key="", environment="test")
    ensure_secure_configuration(settings)


def test_development_with_empty_keys_raises() -> None:
    settings = make_settings(environment="development", jwt_signing_key="", totp_encryption_key="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings, exempt_environments=frozenset())
    assert "jwt_signing_key" in str(raised.value)


def test_exempt_environments_constant_includes_test() -> None:
    assert CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS == frozenset({"test"})
