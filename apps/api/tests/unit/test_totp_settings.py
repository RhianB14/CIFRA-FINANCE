import pyotp
import pytest
from cryptography.fernet import Fernet

import app.core.totp as totp_module
from app.core.settings import Settings
from app.core.totp import provisioning_uri, verify_totp


def make_settings(**overrides: str) -> Settings:
    defaults: dict[str, str] = {
        "jwt_signing_key": "unit-test-signing-key-0123456789abcdef0123456789abcdef",
        "totp_encryption_key": Fernet.generate_key().decode(),
        "environment": "production",
    }
    merged = {**defaults, **overrides}
    return Settings.model_validate(merged)


def settings_value(settings: Settings, name: str) -> object:
    return getattr(settings, name, None)


def test_provisioning_uri_uses_configured_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = make_settings(totp_issuer="Cifra-Prod")
    monkeypatch.setattr(totp_module, "get_settings", lambda: configured)
    uri = provisioning_uri("user@example.com", "JBSWY3DPEHPK3PXP")
    assert "issuer=Cifra-Prod" in uri


def test_verify_totp_uses_configured_period(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = make_settings(totp_period="60")
    monkeypatch.setattr(totp_module, "get_settings", lambda: configured)
    seed = "JBSWY3DPEHPK3PXP"
    totp = pyotp.TOTP(seed, interval=60)
    now = 1_000_000
    step = int(now // 60)
    code = totp.at(step * 60)
    accepted, used_step = verify_totp(seed, code, last_step=None, now=float(now))
    assert accepted is True
    assert used_step == step


def test_verify_totp_rejects_code_beyond_configured_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = make_settings(totp_drift_seconds="30", totp_period="30")
    monkeypatch.setattr(totp_module, "get_settings", lambda: configured)
    seed = "JBSWY3DPEHPK3PXP"
    totp = pyotp.TOTP(seed, interval=30)
    now = 1_000_000
    older = totp.at(now - 120)
    accepted, _ = verify_totp(seed, older, last_step=None, now=float(now))
    assert accepted is False


def test_verify_totp_accepts_within_configured_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = make_settings(totp_drift_seconds="90", totp_period="30")
    monkeypatch.setattr(totp_module, "get_settings", lambda: configured)
    seed = "JBSWY3DPEHPK3PXP"
    totp = pyotp.TOTP(seed, interval=30)
    now = 1_000_000
    older = totp.at(now - 60)
    accepted, used_step = verify_totp(seed, older, last_step=None, now=float(now))
    assert accepted is True
    assert used_step == int((now - 60) // 30)


def test_settings_carries_totp_period_field() -> None:
    settings = make_settings(totp_period="45")
    assert settings_value(settings, "totp_period") == 45
