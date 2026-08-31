from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.emails import normalize_email
from app.core.passwords import hash_password, validate_password, verify_password
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
) -> tuple[User, str, str]:
    validate_password(password)
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
    access = create_access_token(user.id)
    refresh, _ = await issue_refresh_token(session, user.id)
    try:
        await session.commit()
    except IntegrityError as error:
        raise EmailAlreadyRegisteredError("email is already registered") from error
    await session.refresh(user)
    return user, access, refresh


async def start_session(session: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user.id)
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
    return user
