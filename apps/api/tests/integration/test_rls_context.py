import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.db import bind_current_user, set_bypass_scope


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
    assert result.scalar_one() == str(user_id)
    other = await db_session.execute(text("SELECT current_setting('app.auth_scope', true)"))
    assert other.scalar_one() == ""


@pytest.mark.asyncio
async def test_session_scope_never_leaks_to_new_session(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    async with factory() as bound:
        await bind_current_user(bound, uuid.uuid4())
        await bound.commit()
    async with factory() as fresh:
        result = await fresh.execute(text("SELECT current_setting('app.current_user_id', true)"))
        assert result.scalar_one() in (None, "")


@pytest.mark.asyncio
async def test_rls_enabled_on_users_table(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'users'::regclass"
        )
    )
    row = result.one()
    assert row[0] is True
    assert row[1] is True


@pytest.mark.asyncio
async def test_rls_enabled_on_audit_events_table(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'audit_events'::regclass"
        )
    )
    row = result.one()
    assert row[0] is True
    assert row[1] is True


@pytest.mark.asyncio
async def test_policies_exist_for_protected_tables(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT tablename, policyname FROM pg_policies "
            "WHERE schemaname = 'public' "
            "AND tablename IN ('users', 'audit_events') "
            "ORDER BY tablename, policyname"
        )
    )
    rows = result.all()
    assert len(rows) >= 2


@pytest.mark.asyncio
async def test_unbound_session_sees_zero_users(db_session: AsyncSession) -> None:

    await bind_current_user(db_session, uuid.uuid4())
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_unbound_session_sees_zero_audit_events(db_session: AsyncSession) -> None:
    await bind_current_user(db_session, uuid.uuid4())
    result = await db_session.execute(text("SELECT count(*) FROM audit_events"))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_rows(db_session: AsyncSession) -> None:
    from sqlalchemy import select

    from app.core.passwords import hash_password
    from app.models import User

    user_a = User(
        email="rls-a@example.com",
        name="A",
        password_hash=hash_password("Tr0ub4dor&3-RLS-A"),
    )
    user_b = User(
        email="rls-b@example.com",
        name="B",
        password_hash=hash_password("Tr0ub4dor&3-RLS-B"),
    )
    await set_bypass_scope(db_session)
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    await bind_current_user(db_session, user_a.id)
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert len(users) == 1
    assert users[0].id == user_a.id


@pytest.mark.asyncio
async def test_superuser_bypass_is_absent_from_policies(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT policyname, roles FROM pg_policies "
            "WHERE schemaname = 'public' "
            "AND tablename IN ('users', 'audit_events')"
        )
    )
    for _policy, roles in result.all():
        assert "admin" not in roles


@pytest.mark.asyncio
async def test_pre_auth_flows_use_bypass_scope(db_session: AsyncSession) -> None:
    from sqlalchemy import select

    from app.core.passwords import hash_password
    from app.models import User

    user = User(
        email="rls-preauth@example.com",
        name="P",
        password_hash=hash_password("Tr0ub4dor&3-RLS-P"),
    )
    await set_bypass_scope(db_session)
    db_session.add(user)
    await db_session.commit()

    await set_bypass_scope(db_session)
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert len(users) == 1
    assert users[0].id == user.id
