import uuid

import pytest
import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.emails import normalize_email
from app.core.passwords import verify_password
from app.core.settings import get_settings
from app.models import User
from app.services.password_reset import (
    ResetStoreUnavailableError,
    ResetTokenInvalidError,
    consume_reset_token,
    issue_reset_token,
    reset_password,
)

PASSWORD = "correct horse battery staple"


async def make_user(session: AsyncSession, email: str = "reset@example.com") -> User:
    from app.core.passwords import hash_password

    user = User(
        email=normalize_email(email),
        name="Ana",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    return user


def redis_store() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


@pytest.mark.asyncio
async def test_issue_returns_raw_token_and_stores_hash_only(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    store = redis_store()
    try:
        token = await issue_reset_token(store, user.id)
        assert isinstance(token, str)
        assert len(token) >= 43
        keys = [key async for key in store.scan_iter(match="cifra:reset:*")]
        assert len(keys) == 1
        stored = await store.get(keys[0])
        assert stored is not None
        assert stored != token
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_issue_for_unknown_email_yields_unstored_token(db_session: AsyncSession) -> None:
    store = redis_store()
    try:
        token = await issue_reset_token(store, uuid.uuid4())
        assert isinstance(token, str)
        keys = [key async for key in store.scan_iter(match="cifra:reset:*")]
        assert len(keys) == 0
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_reset_password_rotates_credentials(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    store = redis_store()
    try:
        token = await issue_reset_token(store, user.id)
        await reset_password(db_session, store, token, "brand new password value")
        await db_session.commit()
        await db_session.refresh(user)
        assert verify_password(user.password_hash, "brand new password value")
        keys = [key async for key in store.scan_iter(match="cifra:reset:*")]
        assert len(keys) == 0
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_reset_token_is_single_use(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    store = redis_store()
    try:
        token = await issue_reset_token(store, user.id)
        await reset_password(db_session, store, token, "brand new password value")
        await db_session.commit()
        with pytest.raises(ResetTokenInvalidError):
            await reset_password(db_session, store, token, "another new password")
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_invalid_token_raises_typed_error(db_session: AsyncSession) -> None:
    store = redis_store()
    try:
        with pytest.raises(ResetTokenInvalidError):
            await consume_reset_token(store, "not-a-real-token")
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_store_failure_raises_typed_error(db_session: AsyncSession) -> None:
    class BrokenStore:
        async def getdel(self, *args: object, **kwargs: object) -> str | None:
            raise RedisError("store down")

        async def set(self, *args: object, **kwargs: object) -> object:
            raise RedisError("store down")

    with pytest.raises(ResetStoreUnavailableError):
        await consume_reset_token(BrokenStore(), "any-token")
    with pytest.raises(ResetStoreUnavailableError):
        await issue_reset_token(BrokenStore(), uuid.uuid4())
