import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, Transaction, User
from app.services.ledger import apply_transfer


def occurred() -> datetime:
    return datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


async def _make_pair(db_session: AsyncSession) -> tuple[Account, Account]:
    user = User(
        email=f"opp-{uuid.uuid4().hex[:10]}@example.com",
        name="Opp",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    first = Account(
        user_id=user.id,
        name="Opp A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=70000,
        current_balance_cents=70000,
        current_balance_version=0,
    )
    second = Account(
        user_id=user.id,
        name="Opp B",
        kind="checking",
        currency="BRL",
        initial_balance_cents=30000,
        current_balance_cents=30000,
        current_balance_version=0,
    )
    db_session.add(first)
    db_session.add(second)
    await db_session.commit()
    return first, second


@pytest.mark.asyncio
async def test_opposite_transfers_do_not_deadlock(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    for _ in range(8):
        account_a, account_b = await _make_pair(db_session)
        factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
        barrier = asyncio.Barrier(2)

        async def run_transfer(
            src: Account,
            dst: Account,
            key: str,
            session_factory: async_sessionmaker[AsyncSession] = factory,
            start_gate: asyncio.Barrier = barrier,
        ) -> None:
            async with session_factory() as session:
                await set_bypass_scope(session)
                await start_gate.wait()
                await apply_transfer(
                    session,
                    from_account_id=src.id,
                    to_account_id=dst.id,
                    user_id=src.user_id,
                    idempotency_key=key,
                    amount_cents=10000,
                    occurred_at=occurred(),
                )
                await session.commit()

        await asyncio.gather(
            run_transfer(account_a, account_b, f"opp-out-{uuid.uuid4().hex[:8]}"),
            run_transfer(account_b, account_a, f"opp-back-{uuid.uuid4().hex[:8]}"),
        )

        async with factory() as verifier:
            await set_bypass_scope(verifier)
            accounts = (
                (
                    await verifier.execute(
                        select(Account).where(Account.id.in_([account_a.id, account_b.id]))
                    )
                )
                .scalars()
                .all()
            )
            balances = {account.id: account for account in accounts}
            assert balances[account_a.id].current_balance_cents == 70000
            assert balances[account_b.id].current_balance_cents == 30000
            assert balances[account_a.id].current_balance_version == 2
            assert balances[account_b.id].current_balance_version == 2
            legs = (
                (
                    await verifier.execute(
                        select(Transaction).where(
                            Transaction.transfer_group_id.is_not(None),
                            Transaction.account_id.in_([account_a.id, account_b.id]),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(legs) == 4
        groups: dict[uuid.UUID, list[Transaction]] = {}
        for leg in legs:
            assert leg.transfer_group_id is not None
            groups.setdefault(leg.transfer_group_id, []).append(leg)
        assert len(groups) == 2
        for group_legs in groups.values():
            assert sorted(leg.kind.strip() for leg in group_legs) == ["credit", "debit"]
