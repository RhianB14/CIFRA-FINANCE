import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import (
    F1_TABLES,
    alembic_config,
    async_url,
    recreate_database,
)

REVISION = "0001"


async def fetch_int(url: str, sql: str) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return int(result.scalar_one())
    finally:
        await engine.dispose()


@pytest.fixture()
async def migration_db() -> AsyncIterator[str]:
    database = "cifra_test_security_migration"
    await recreate_database(database)
    yield database
    engine = create_async_engine(async_url(database))
    await engine.dispose()


async def test_upgrade_creates_all_f1_tables(migration_db: str) -> None:
    await asyncio.to_thread(command.upgrade, alembic_config(migration_db), "head")
    engine = create_async_engine(async_url(migration_db))
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
            names = {str(row[0]) for row in rows}
    finally:
        await engine.dispose()
    assert set(F1_TABLES) <= names
    assert "alembic_version" in names


async def test_downgrade_removes_all_f1_tables(migration_db: str) -> None:
    await asyncio.to_thread(command.upgrade, alembic_config(migration_db), "head")
    await asyncio.to_thread(command.downgrade, alembic_config(migration_db), "base")
    engine = create_async_engine(async_url(migration_db))
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
            names = {str(row[0]) for row in rows}
    finally:
        await engine.dispose()
    assert set(F1_TABLES).isdisjoint(names)


async def test_upgrade_downgrade_upgrade_is_idempotent(migration_db: str) -> None:
    configuration = alembic_config(migration_db)
    await asyncio.to_thread(command.upgrade, configuration, "head")
    await asyncio.to_thread(command.downgrade, configuration, "base")
    await asyncio.to_thread(command.upgrade, configuration, "head")
    assert (
        await fetch_int(
            async_url(migration_db),
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'users'",
        )
        == 1
    )
