import uuid

import pytest
from argon2 import PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user
from app.core.passwords import verify_password
from app.models import User
from app.services.auth import AuthenticationError, authenticate_user

PASSWORD = "Tr0ub4dor&3-Correct-Horse"


async def old_hash_user(session: AsyncSession) -> User:
    old_hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    user = User(
        email=f"rehash-{uuid.uuid4().hex}@example.com",
        name="Ana",
        password_hash=old_hasher.hash(PASSWORD),
    )
    session.add(user)
    await session.commit()
    await bind_current_user(session, user.id)
    return user


@pytest.mark.asyncio
async def test_login_rehashes_old_argon2_hash(db_session: AsyncSession) -> None:
    user = await old_hash_user(db_session)
    original = user.password_hash
    authenticated = await authenticate_user(db_session, user.email, PASSWORD)
    await db_session.refresh(authenticated)
    assert authenticated.password_hash != original
    assert verify_password(authenticated.password_hash, PASSWORD) is True


@pytest.mark.asyncio
async def test_wrong_password_never_rehashes(db_session: AsyncSession) -> None:
    user = await old_hash_user(db_session)
    original = user.password_hash
    with pytest.raises(AuthenticationError):
        await authenticate_user(db_session, user.email, "Wrong-Password-123")
    await db_session.refresh(user)
    assert user.password_hash == original
