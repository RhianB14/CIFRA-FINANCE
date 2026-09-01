import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import bind_current_user, get_engine
from app.core.passwords import hash_password
from app.models import User
from app.services.session_revocation import session_invalid


@pytest.fixture
async def app_role_session() -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    session = maker()
    await session.execute(text("SET ROLE cifra_app"))
    try:
        yield session
    finally:
        await session.rollback()
        await session.execute(text("RESET ROLE"))
        await session.close()


async def make_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        name="Scope",
        password_hash=hash_password("CorrectHorse-9x!LongEnough"),
    )
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_session_invalid_fail_closed_without_scope(
    db_session: AsyncSession, app_role_session: AsyncSession
) -> None:
    user = await make_user(db_session, "unscoped-sv@example.com")

    assert await session_invalid(app_role_session, user.id, user.session_version) is True


@pytest.mark.asyncio
async def test_session_invalid_false_after_bind(
    db_session: AsyncSession, app_role_session: AsyncSession
) -> None:
    user = await make_user(db_session, "bound-sv@example.com")

    await bind_current_user(app_role_session, user.id)
    bound = await app_role_session.get(User, user.id)
    assert bound is not None
    assert await session_invalid(app_role_session, user.id, user.session_version) is False


@pytest.mark.asyncio
async def test_session_invalid_true_when_version_diverges(
    db_session: AsyncSession, app_role_session: AsyncSession
) -> None:
    user = await make_user(db_session, "stale-sv@example.com")

    await bind_current_user(app_role_session, user.id)
    stale_version = user.session_version + 1
    assert await session_invalid(app_role_session, user.id, stale_version) is True


@pytest.mark.asyncio
async def test_unknown_user_still_reports_invalid(
    db_session: AsyncSession, app_role_session: AsyncSession
) -> None:
    await bind_current_user(app_role_session, uuid.uuid4())
    assert await session_invalid(app_role_session, uuid.uuid4(), 1) is True
