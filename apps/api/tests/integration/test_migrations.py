import asyncio

from alembic import command

from tests.conftest import F1_TABLES, alembic_config, async_url, recreate_database, table_names


async def test_upgrade_downgrade_upgrade_against_real_postgres() -> None:
    database = "cifra_test_migration"
    await recreate_database(database)
    configuration = alembic_config(database)

    await asyncio.to_thread(command.upgrade, configuration, "head")
    assert set(F1_TABLES) <= await table_names(async_url(database))

    await asyncio.to_thread(command.downgrade, configuration, "base")
    assert not (set(F1_TABLES) & await table_names(async_url(database)))

    await asyncio.to_thread(command.upgrade, configuration, "head")
    assert set(F1_TABLES) <= await table_names(async_url(database))
