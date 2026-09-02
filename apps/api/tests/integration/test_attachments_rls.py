import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, User


async def _make_two_users_with_accounts(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user_a = User(
        email=f"rls-a-{uuid.uuid4().hex[:10]}@example.com",
        name="RLS A",
        password_hash="x" * 20,
    )
    user_b = User(
        email=f"rls-b-{uuid.uuid4().hex[:10]}@example.com",
        name="RLS B",
        password_hash="x" * 20,
    )
    db_session.add_all([user_a, user_b])
    await db_session.commit()
    account_a = Account(
        user_id=user_a.id,
        name="Conta A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    account_b = Account(
        user_id=user_b.id,
        name="Conta B",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    db_session.add_all([account_a, account_b])
    await db_session.commit()
    return user_a.id, user_b.id


@pytest.mark.asyncio
async def test_domain_tables_force_row_level_security(db_session: AsyncSession) -> None:
    forced = await db_session.execute(
        text(
            "SELECT relname FROM pg_class"
            " WHERE relnamespace = 'public'::regnamespace"
            " AND relrowsecurity = true AND relforcerowsecurity = true"
        )
    )
    forced_names = {row[0] for row in forced}
    for table in (
        "accounts",
        "transactions",
        "categories",
        "tags",
        "import_batches",
        "account_balance_snapshots",
        "attachments",
    ):
        assert table in forced_names, f"table {table} without force row level security"


@pytest.mark.asyncio
async def test_admin_bypass_reads_across_users_after_force(
    db_session: AsyncSession,
) -> None:
    user_a_id, _user_b_id = await _make_two_users_with_accounts(db_session)
    await db_session.execute(
        text(
            "SELECT set_config('app.current_user_id', :uid, true),"
            " set_config('app.auth_scope', 'bypass', true)"
        ),
        {"uid": str(user_a_id)},
    )
    rows = await db_session.execute(text("SELECT COUNT(*) FROM accounts"))
    assert rows.scalar_one() >= 2


@pytest.mark.asyncio
async def test_table_owner_without_bypass_is_filtered_by_force_rls(
    db_session: AsyncSession,
) -> None:
    user_a_id, user_b_id = await _make_two_users_with_accounts(db_session)
    await db_session.execute(
        text(
            "SELECT set_config('app.current_user_id', :uid, true),"
            " set_config('app.auth_scope', 'tenant', true)"
        ),
        {"uid": str(user_a_id)},
    )
    await db_session.execute(text("SAVEPOINT rls_probe"))
    try:
        visible = await db_session.execute(text("SELECT COUNT(*) FROM accounts"))
        assert visible.scalar_one() == 1
        others = await db_session.execute(
            text("SELECT COUNT(*) FROM accounts WHERE user_id = :other"),
            {"other": str(user_b_id)},
        )
        assert others.scalar_one() == 0
    finally:
        await db_session.execute(text("ROLLBACK TO SAVEPOINT rls_probe"))
