import asyncio

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.conftest import admin_dsn, alembic_config, recreate_database


def _head_revision() -> str:
    configuration = Config("alembic.ini")
    configuration.set_main_option("script_location", "migrations")
    return str(ScriptDirectory.from_config(configuration).get_current_head())


async def _seed_f2_rows(database: str) -> None:
    conn = await asyncpg.connect(admin_dsn(database))
    try:
        await conn.execute(
            "INSERT INTO users (id, email, name, password_hash)"
            " VALUES (gen_random_uuid(), 'mig@example.com', 'Mig', repeat('x', 20))"
        )
        await conn.execute(
            "INSERT INTO accounts (id, user_id, name, kind, currency,"
            " initial_balance_cents, current_balance_cents, current_balance_version)"
            " SELECT gen_random_uuid(), id, 'Mig Src', 'checking', 'BRL', 100000, 70000, 1"
            " FROM users WHERE email = 'mig@example.com'"
        )
        await conn.execute(
            "INSERT INTO accounts (id, user_id, name, kind, currency,"
            " initial_balance_cents, current_balance_cents, current_balance_version)"
            " SELECT gen_random_uuid(), id, 'Mig Dst', 'checking', 'BRL', 0, 30000, 1"
            " FROM users WHERE email = 'mig@example.com'"
        )
        await conn.execute(
            "INSERT INTO transactions (id, user_id, account_id, idempotency_key,"
            " payload_signature, kind, operation_type, status, amount_cents, occurred_at,"
            " result_balance_after_cents, result_balance_version)"
            " SELECT gen_random_uuid(), u.id, a.id, 'mig-out', 'sig', 'debit',"
            " 'transfer_out', 'posted', 30000, now(), 70000, 1"
            " FROM users u JOIN accounts a ON a.user_id = u.id AND a.name = 'Mig Src'"
            " WHERE u.email = 'mig@example.com'"
        )
        await conn.execute(
            "INSERT INTO transactions (id, user_id, account_id, idempotency_key,"
            " payload_signature, kind, operation_type, status, amount_cents, occurred_at,"
            " result_balance_after_cents, result_balance_version)"
            " SELECT gen_random_uuid(), u.id, a.id, 'mig-in', 'sig', 'credit',"
            " 'transfer_in', 'posted', 30000, now(), 30000, 1"
            " FROM users u JOIN accounts a ON a.user_id = u.id AND a.name = 'Mig Dst'"
            " WHERE u.email = 'mig@example.com'"
        )
    finally:
        await conn.close()


async def _transfer_row_count(database: str) -> int:
    conn = await asyncpg.connect(admin_dsn(database))
    try:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM transactions"
                " WHERE operation_type IN ('transfer_in', 'transfer_out')"
            )
        )
    finally:
        await conn.close()


async def _migration_version(database: str) -> str:
    conn = await asyncpg.connect(admin_dsn(database))
    try:
        return str(await conn.fetchval("SELECT version_num FROM alembic_version"))
    finally:
        await conn.close()


async def test_downgrade_with_transfer_rows_is_rejected_transactionally() -> None:
    database = "cifra_test_migration_f2"
    await recreate_database(database)
    configuration = alembic_config(database)
    await asyncio.to_thread(command.upgrade, configuration, "head")
    await _seed_f2_rows(database)

    with pytest.raises(Exception, match="transfer rows present"):
        await asyncio.to_thread(command.downgrade, configuration, "0004")

    assert await _migration_version(database) == _head_revision()
    assert await _transfer_row_count(database) == 2
