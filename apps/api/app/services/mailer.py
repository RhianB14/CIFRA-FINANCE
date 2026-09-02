import json
from functools import lru_cache
from typing import Protocol
from urllib import request as urlrequest

from app.core.settings import get_settings


class MailerError(Exception):
    pass


class Mailer(Protocol):
    async def send_password_reset(self, email: str, token: str) -> None: ...


class NullMailer:
    async def send_password_reset(self, email: str, token: str) -> None:
        return None


class ResendMailer:
    def __init__(self, bearer: str, sender: str, timeout_seconds: float) -> None:
        self._bearer = bearer
        self._sender = sender
        self._timeout_seconds = timeout_seconds

    async def send_password_reset(self, email: str, token: str) -> None:
        import asyncio

        settings = get_settings()
        body = json.dumps(
            {
                "from": self._sender,
                "to": [email],
                "subject": "CIFRA password reset",
                "text": (
                    "Use this token to reset your password: "
                    f"{token}\nIt expires in {settings.password_reset_ttl_minutes} minutes."
                ),
            }
        ).encode("utf-8")
        req = urlrequest.Request(
            "https://api.resend.com/emails",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._bearer}",
                "Content-Type": "application/json",
            },
        )

        def _send() -> None:
            try:
                with urlrequest.urlopen(req, timeout=self._timeout_seconds) as response:
                    if response.status >= 400:
                        raise MailerError("resend delivery failed")
            except urlrequest.HTTPError as error:
                raise MailerError("resend delivery failed") from error
            except OSError as error:
                raise MailerError("resend delivery failed") from error

        try:
            await asyncio.to_thread(_send)
        except MailerError:
            raise
        except Exception as error:
            raise MailerError("resend delivery failed") from error


@lru_cache
def get_mailer() -> Mailer:
    settings = get_settings()
    if settings.password_reset_resend_enabled:
        if not settings.resend_api_key or not settings.resend_from:
            raise MailerError("resend configuration is incomplete")
        return ResendMailer(
            bearer=settings.resend_api_key,
            sender=settings.resend_from,
            timeout_seconds=settings.external_http_timeout_seconds,
        )
    return NullMailer()
