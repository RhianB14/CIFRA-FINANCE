from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.emails import normalize_email
from app.core.hibp import HIBPClient, HIBPTransport, http_hibp_transport
from app.core.passwords import (
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)
from app.core.settings import get_settings
from app.core.tokens import create_access_token
from app.models import User
from app.services.rotation import issue_refresh_token


class AuthenticationError(Exception):
    pass


class EmailAlreadyRegisteredError(AuthenticationError):
    pass


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalar_one_or_none()


async def register_user(
    session: AsyncSession,
    email: str,
    password: str,
    name: str,
    hibp_enabled: bool | None = None,
    hibp_transport: HIBPTransport | None = None,
) -> tuple[User, str, str]:
    validate_password(password)
    settings = get_settings()
    enabled = settings.hibp_enabled if hibp_enabled is None else hibp_enabled
    if enabled:
        client = HIBPClient(
            transport=hibp_transport if hibp_transport is not None else http_hibp_transport,
            timeout_seconds=settings.hibp_timeout_seconds,
            fail_closed=True,
        )
        if await client.check_password(password):
            raise AuthenticationError("password is compromised")
    normalized = normalize_email(email)
    if await get_user_by_email(session, normalized) is not None:
        raise EmailAlreadyRegisteredError("email is already registered")
    user = User(
        email=normalized,
        name=name.strip(),
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()
    access = create_access_token(user.id, session_version=user.session_version)
    refresh, _ = await issue_refresh_token(session, user.id)
    try:
        await session.commit()
    except IntegrityError as error:
        raise EmailAlreadyRegisteredError("email is already registered") from error
    await session.refresh(user)
    return user, access, refresh


async def start_session(session: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user.id, session_version=user.session_version)
    refresh, _ = await issue_refresh_token(session, user.id)
    await session.commit()
    return access, refresh


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User:
    user = await get_user_by_email(session, email)
    if user is None or not verify_password(user.password_hash, password):
        raise AuthenticationError("invalid credentials")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await session.commit()
    return user
