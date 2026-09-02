import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, User
from app.services.csv_import import import_csv


def _csv_content() -> bytes:
    return (
        b"occurred_at,amount_cents,kind,description,external_id\n"
        b"2026-09-01T10:00:00+00:00,500,credit,pagamento aluguel,ext-1\n"
        b"2026-09-02T10:00:00+00:00,120,debit,compra mercado,ext-2\n"
    )


async def _make_account(db_session: AsyncSession) -> Account:
    user = User(
        email=f"imprace-{uuid.uuid4().hex[:10]}@example.com",
        name="Imp Race",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Imp Race A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return account


@pytest.mark.asyncio
async def test_concurrent_same_file_import_returns_single_batch(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    for _ in range(5):
        account = await _make_account(db_session)
        content = _csv_content()
        factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

        async def run_import(
            acct: Account = account,
            payload: bytes = content,
            session_factory: async_sessionmaker[AsyncSession] = factory,
        ) -> tuple[uuid.UUID, int]:
            async with session_factory() as session:
                await set_bypass_scope(session)
                result = await import_csv(
                    session,
                    account_id=acct.id,
                    user_id=acct.user_id,
                    source_name="banco-x",
                    file_name="race.csv",
                    content=payload,
                )
                await session.commit()
                return result.batch_id, result.imported_count

        first, second = await asyncio.gather(run_import(), run_import())

        assert first[0] == second[0]
        assert {first[1], second[1]} == {2, 0}
