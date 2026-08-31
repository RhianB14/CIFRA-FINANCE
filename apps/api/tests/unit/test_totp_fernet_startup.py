import base64

import pytest
from cryptography.fernet import Fernet

from app.core.settings import Settings, ensure_secure_configuration


def make_settings(**overrides: str) -> Settings:
    defaults: dict[str, str] = {
        "jwt_signing_key": "unit-test-signing-key-0123456789abcdef0123456789abcdef",
        "totp_encryption_key": Fernet.generate_key().decode(),
        "environment": "production",
    }
    merged = {**defaults, **overrides}
    return Settings.model_validate(merged)


def test_rejects_totp_key_that_is_not_valid_fernet() -> None:
    settings = make_settings(totp_encryption_key="not-a-fernet-key")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_encryption_key" in str(raised.value)


def test_rejects_totp_key_with_wrong_padding() -> None:
    raw = base64.urlsafe_b64encode(b"short").decode().rstrip("=")
    settings = make_settings(totp_encryption_key=raw)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_encryption_key" in str(raised.value)


def test_accepts_valid_fernet_totp_key() -> None:
    ensure_secure_configuration(make_settings())
