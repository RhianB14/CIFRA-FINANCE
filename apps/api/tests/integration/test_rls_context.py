import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user


@pytest.mark.asyncio
async def test_current_user_setting_is_absent_before_bind(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT current_setting('app.current_user_id', true)"))
    assert result.scalar_one() in (None, "")


@pytest.mark.asyncio
async def test_bind_current_user_sets_local_config(db_session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    await bind_current_user(db_session, user_id)
    result = await db_session.execute(text("SELECT current_setting('app.current_user_id', true)"))
    assert result.scalar_one() == str(user_id)


@pytest.mark.asyncio
async def test_bind_current_user_scopes_to_transaction(db_session: AsyncSession) -> None:
    user_id = uuid.uuid4()
    await bind_current_user(db_session, user_id)
    await db_session.commit()
    result = await db_session.execute(text("SELECT current_setting('app.current_user_id', true)"))
    assert result.scalar_one() in (None, "")
