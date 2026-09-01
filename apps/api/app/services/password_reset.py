from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ResetTokenInvalidError(Exception):
    pass


class ResetStoreUnavailableError(Exception):
    pass


class Mailer(Protocol):
    async def send_password_reset(self, email: str, token: str) -> None: ...


class NullMailer:
    async def send_password_reset(self, email: str, token: str) -> None:
        raise NotImplementedError


def get_mailer() -> Mailer:
    raise NotImplementedError


async def issue_reset_token(
    store: object,
    user_id: object,
) -> str:
    raise NotImplementedError


async def consume_reset_token(store: object, token: str) -> AsyncSession | None:
    raise NotImplementedError


async def reset_password(
    session: AsyncSession,
    store: object,
    token: str,
    new_password: str,
) -> None:
    raise NotImplementedError
