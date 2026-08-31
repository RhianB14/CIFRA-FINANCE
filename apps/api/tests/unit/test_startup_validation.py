import pytest
from cryptography.fernet import Fernet

import app.core.settings as settings_module
from app.main import app


async def test_startup_fails_without_signing_key_outside_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_module, "CONFIG_VALIDATION_EXEMPT_ENVIRONMENTS", frozenset())
    monkeypatch.setenv("JWT_SIGNING_KEY", "")
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", "")
    settings_module.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            async with app.router.lifespan_context(app):
                pass
    finally:
        settings_module.get_settings.cache_clear()


async def test_startup_passes_with_strong_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", "a" * 48)
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings_module.get_settings.cache_clear()
    try:
        async with app.router.lifespan_context(app):
            pass
    finally:
        settings_module.get_settings.cache_clear()
