from typing import Any
from unittest.mock import patch

import pytest

from app.core.settings import get_settings
from app.services.mailer import MailerError, NullMailer, ResendMailer, get_mailer


@pytest.mark.asyncio
async def test_null_mailer_is_silent_no_op() -> None:
    mailer = NullMailer()
    await mailer.send_password_reset("a@example.com", "t")


@pytest.mark.asyncio
async def test_resend_mailer_posts_expected_payload() -> None:
    mailer = ResendMailer(bearer="b" * 20, sender="no-reply@example.com", timeout_seconds=1.0)
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float) -> Any:
        captured["url"] = req.full_url
        captured["body"] = req.data.decode("utf-8")
        captured["auth"] = req.headers.get("Authorization")
        captured["timeout"] = timeout

        class Resp:
            status = 200

            def __enter__(self) -> "Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        return Resp()

    with patch("app.services.mailer.urlrequest.urlopen", side_effect=fake_urlopen):
        await mailer.send_password_reset("a@example.com", "tok-value")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer " + "b" * 20
    assert '"to": ["a@example.com"]' in captured["body"]
    assert "tok-value" in captured["body"]
    assert captured["timeout"] == 1.0


@pytest.mark.asyncio
async def test_resend_mailer_maps_http_error_to_mailer_error() -> None:
    from email.message import Message
    from urllib import error as urlerror

    mailer = ResendMailer(bearer="b" * 20, sender="no-reply@example.com", timeout_seconds=1.0)
    headers = Message()
    with patch(
        "app.services.mailer.urlrequest.urlopen",
        side_effect=urlerror.HTTPError("url", 422, "bad", headers, None),
    ):
        with pytest.raises(MailerError):
            await mailer.send_password_reset("a@example.com", "tok-value")


@pytest.mark.asyncio
async def test_resend_mailer_maps_network_error_to_mailer_error() -> None:
    mailer = ResendMailer(bearer="b" * 20, sender="no-reply@example.com", timeout_seconds=1.0)
    with patch("app.services.mailer.urlrequest.urlopen", side_effect=OSError("dns down")):
        with pytest.raises(MailerError):
            await mailer.send_password_reset("a@example.com", "tok-value")


def test_get_mailer_returns_null_when_disabled() -> None:
    get_mailer.cache_clear()
    assert isinstance(get_mailer(), NullMailer)


def test_get_mailer_requires_configuration_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    get_mailer.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "password_reset_resend_enabled", True)
    with pytest.raises(MailerError):
        get_mailer()
    get_mailer.cache_clear()
