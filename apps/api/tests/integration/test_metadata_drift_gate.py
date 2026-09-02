import asyncio

from alembic import command

from tests.conftest import alembic_config, recreate_database


async def test_base_metadata_matches_migrated_schema() -> None:
    database = "cifra_test_meta_check"
    await recreate_database(database)
    configuration = alembic_config(database)
    await asyncio.to_thread(command.upgrade, configuration, "head")
    await asyncio.to_thread(command.check, configuration)
