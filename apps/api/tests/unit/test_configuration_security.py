from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.core.settings import Settings, ensure_secure_configuration


def make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "jwt_signing_key": "unit-test-signing-key-0123456789abcdef0123456789abcdef",
        "totp_encryption_key": Fernet.generate_key().decode(),
        "backup_code_pepper": "unit-test-pepper-0123456789abcdef0123456789abcdef",
        "environment": "production",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_accepts_strong_configuration_in_production() -> None:
    ensure_secure_configuration(make_settings())


def test_rejects_empty_pepper() -> None:
    settings = make_settings(backup_code_pepper="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_rejects_short_pepper() -> None:
    settings = make_settings(backup_code_pepper="short-pepper")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_pepper_minimum_is_measured_in_bytes_not_characters() -> None:
    sixteen_multibyte_characters = "ã" * 16
    assert len(sixteen_multibyte_characters) < 32
    assert len(sixteen_multibyte_characters.encode("utf-8")) >= 32
    ensure_secure_configuration(make_settings(backup_code_pepper=sixteen_multibyte_characters))


def test_rejects_pepper_equal_to_jwt_signing_key() -> None:
    shared = "shared-secret-0123456789abcdef0123456789abcdef"
    settings = make_settings(jwt_signing_key=shared, backup_code_pepper=shared)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_rejects_pepper_equal_to_fernet_key() -> None:
    shared = Fernet.generate_key().decode()
    settings = make_settings(totp_encryption_key=shared, backup_code_pepper=shared)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_rejects_development_pepper_in_production() -> None:
    settings = make_settings(
        backup_code_pepper="dev-only-backup-code-pepper-change-me-0123456789abcdef"
    )
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_rejects_development_pepper_with_multibyte_disguise() -> None:
    settings = make_settings(
        backup_code_pepper="dev-only-backup-code-pepper-change-me-0123456789abcdeã"
    )
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "backup_code_pepper" in str(raised.value)


def test_rejects_non_positive_totp_period() -> None:
    settings = make_settings(totp_period=0)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_period" in str(raised.value)


def test_rejects_negative_totp_drift_seconds() -> None:
    settings = make_settings(totp_drift_seconds=-1)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "totp_drift_seconds" in str(raised.value)


def test_rejects_non_positive_access_token_ttl() -> None:
    settings = make_settings(access_token_ttl_minutes=0)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "access_token_ttl_minutes" in str(raised.value)


def test_rejects_non_positive_refresh_token_ttl() -> None:
    settings = make_settings(refresh_token_ttl_days=0)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "refresh_token_ttl_days" in str(raised.value)


def test_rejects_non_positive_challenge_ttl() -> None:
    settings = make_settings(two_factor_challenge_ttl_seconds=0)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "two_factor_challenge_ttl_seconds" in str(raised.value)


def test_rejects_non_positive_hibp_timeout() -> None:
    settings = make_settings(hibp_timeout_seconds=0.0)
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    assert "hibp_timeout_seconds" in str(raised.value)


def test_collects_all_problems_before_raising() -> None:
    settings = make_settings(
        jwt_signing_key="",
        totp_encryption_key="",
        backup_code_pepper="",
        totp_period=0,
        totp_drift_seconds=-1,
        access_token_ttl_minutes=0,
        refresh_token_ttl_days=0,
        two_factor_challenge_ttl_seconds=0,
        hibp_timeout_seconds=0.0,
    )
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    for field in (
        "jwt_signing_key",
        "totp_encryption_key",
        "backup_code_pepper",
        "totp_period",
        "totp_drift_seconds",
        "access_token_ttl_minutes",
        "refresh_token_ttl_days",
        "two_factor_challenge_ttl_seconds",
        "hibp_timeout_seconds",
    ):
        assert field in str(raised.value)


def test_production_cors_problem_is_reported_exactly_once() -> None:
    settings = make_settings(cors_allowed_origins="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    message = str(raised.value)
    assert message.count("cors_allowed_origins must list at least one origin") == 1


def test_trust_proxy_problem_is_reported_exactly_once() -> None:
    settings = make_settings(trust_proxy_headers=True, trusted_proxies="")
    with pytest.raises(RuntimeError) as raised:
        ensure_secure_configuration(settings)
    message = str(raised.value)
    assert message.count("trusted_proxies must list at least one proxy") == 1
