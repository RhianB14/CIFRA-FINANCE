import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, RecurringTransaction, User
from app.services.recurring import (
    RecurringError,
    advance_date,
    create_recurring,
    materialize_recurring,
)


async def _make_user_and_account(db_session: AsyncSession) -> Account:
    user = User(
        email=f"mat-{uuid.uuid4().hex[:10]}@example.com",
        name="Mat Flow",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Mat A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return account


async def _posted_rows(session: AsyncSession, account_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await session.execute(
        text(
            "SELECT idempotency_key, amount_cents FROM transactions"
            " WHERE account_id = :id ORDER BY occurred_at, created_at"
        ),
        {"id": account_id},
    )
    return [(str(k), int(a)) for k, a in rows.all()]


@pytest.mark.asyncio
async def test_monthly_day5_materializes_exactly_three_months(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    recurring = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=10000,
        recurrence="monthly",
        starts_on=date(2026, 8, 5),
    )
    await db_session.commit()

    result = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 10, 31)
    )
    await db_session.commit()
    assert result.created == 3
    assert result.replayed == 0

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 3
    keys = {k for k, _ in rows}
    assert keys == {
        f"recurring:{recurring.id}:2026-08-05",
        f"recurring:{recurring.id}:2026-09-05",
        f"recurring:{recurring.id}:2026-10-05",
    }
    assert all(amount == 10000 for _, amount in rows)

    await db_session.refresh(account)
    assert account.current_balance_cents == 30000
    assert account.current_balance_version == 3


@pytest.mark.asyncio
async def test_rerun_materialization_creates_nothing_new(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    recurring = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=10000,
        recurrence="monthly",
        starts_on=date(2026, 8, 5),
    )
    await db_session.commit()
    first = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 10, 31)
    )
    await db_session.commit()
    assert first.created == 3

    rerun = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 10, 31)
    )
    await db_session.commit()
    assert rerun.created == 0
    assert rerun.replayed == 0

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 3
    assert await _next_run(db_session, recurring.id) == date(2026, 11, 5)


async def _next_run(session: AsyncSession, recurring_id: uuid.UUID) -> date:
    row = await session.execute(
        text("SELECT next_run_on FROM recurring_transactions WHERE id = :id"),
        {"id": recurring_id},
    )
    value = row.scalar_one()
    assert isinstance(value, date)
    return value


@pytest.mark.asyncio
async def test_concurrent_materialization_never_duplicates(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    for _ in range(3):
        account = await _make_user_and_account(db_session)
        await set_bypass_scope(db_session)
        await create_recurring(
            db_session,
            user_id=account.user_id,
            account_id=account.id,
            template_operation_type="deposit",
            template_amount_cents=5000,
            recurrence="daily",
            starts_on=date(2026, 9, 1),
        )
        await db_session.commit()
        factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

        async def run_job(
            session_factory: async_sessionmaker[AsyncSession] = factory,
            owner_id: uuid.UUID = account.user_id,
        ) -> tuple[int, int]:
            async with session_factory() as session:
                await set_bypass_scope(session)
                outcome = await materialize_recurring(
                    session, user_id=owner_id, today=date(2026, 9, 3)
                )
                await session.commit()
                return outcome.created, outcome.replayed

        first, second = await asyncio.gather(run_job(), run_job())

        rows = await _posted_rows(db_session, account.id)
        assert len(rows) == 3
        assert len({k for k, _ in rows}) == 3
        assert first[0] + second[0] == 3
        assert first[0] * second[0] == 0


@pytest.mark.asyncio
async def test_month_end_clamping_is_deterministic(db_session: AsyncSession) -> None:
    assert advance_date(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert advance_date(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)
    assert advance_date(date(2026, 1, 31), "monthly", 3) == date(2026, 4, 30)
    assert advance_date(date(2028, 2, 29), "yearly", 1) == date(2029, 2, 28)
    assert advance_date(date(2028, 2, 29), "yearly", 4) == date(2032, 2, 29)
    assert advance_date(date(2026, 8, 31), "daily", 1) == date(2026, 9, 1)
    assert advance_date(date(2026, 8, 31), "weekly", 1) == date(2026, 9, 7)


@pytest.mark.asyncio
async def test_leap_day_yearly_clamps_to_feb28_in_non_leap_years(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=2900,
        recurrence="yearly",
        starts_on=date(2028, 2, 29),
    )
    await db_session.commit()

    result = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2033, 12, 31)
    )
    await db_session.commit()
    assert result.created == 6

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 6
    assert all(amount == 2900 for _, amount in rows)
    expected = {
        "2028-02-29",
        "2029-02-28",
        "2030-02-28",
        "2031-02-28",
        "2032-02-29",
        "2033-02-28",
    }
    assert {key.rsplit(":", 1)[1] for key, _ in rows} == expected


@pytest.mark.asyncio
async def test_ends_on_stops_materialization(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    recurring = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="withdrawal",
        template_amount_cents=1000,
        recurrence="monthly",
        starts_on=date(2026, 9, 10),
        ends_on=date(2026, 10, 10),
    )
    await db_session.commit()

    result = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2027, 6, 30)
    )
    await db_session.commit()
    assert result.created == 2
    assert await _next_run(db_session, recurring.id) == date(2026, 11, 10)

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 2
    await db_session.refresh(account)
    assert account.current_balance_cents == -2000


@pytest.mark.asyncio
async def test_paused_recurring_skips_then_catches_up_on_reactivation(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    recurring = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=2000,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
    )
    await db_session.commit()
    from sqlalchemy import update as sa_update

    paused = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 9, 30)
    )
    await db_session.commit()
    assert paused.created == 1

    await db_session.execute(
        sa_update(RecurringTransaction)
        .where(RecurringTransaction.id == recurring.id)
        .values(is_active=False)
    )
    await db_session.commit()

    while_paused = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 11, 30)
    )
    await db_session.commit()
    assert while_paused.created == 0

    await db_session.execute(
        sa_update(RecurringTransaction)
        .where(RecurringTransaction.id == recurring.id)
        .values(is_active=True)
    )
    await db_session.commit()

    resumed = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 11, 30)
    )
    await db_session.commit()
    assert resumed.created == 2

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 3
    assert await _next_run(db_session, recurring.id) == date(2026, 12, 5)


@pytest.mark.asyncio
async def test_missed_periods_are_backfilled_and_next_run_advances(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    recurring = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=3000,
        recurrence="weekly",
        starts_on=date(2026, 8, 3),
    )
    await db_session.commit()

    await db_session.execute(
        text("UPDATE recurring_transactions SET next_run_on = :d WHERE id = :id"),
        {"d": date(2026, 8, 3), "id": recurring.id},
    )
    await db_session.commit()

    result = await materialize_recurring(
        db_session, user_id=account.user_id, today=date(2026, 9, 21)
    )
    await db_session.commit()
    assert result.created == 8

    rows = await _posted_rows(db_session, account.id)
    assert len(rows) == 8
    assert len({k for k, _ in rows}) == 8
    assert await _next_run(db_session, recurring.id) == date(2026, 9, 28)


@pytest.mark.asyncio
async def test_materialization_rejects_foreign_user(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=1000,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
    )
    await db_session.commit()

    with pytest.raises(RecurringError, match="not found"):
        await materialize_recurring(db_session, user_id=uuid.uuid4(), today=date(2026, 10, 1))


@pytest.mark.asyncio
async def test_occurred_at_is_noon_utc_deterministic(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=1000,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
    )
    await db_session.commit()

    await materialize_recurring(db_session, user_id=account.user_id, today=date(2026, 9, 5))
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT occurred_at FROM transactions WHERE account_id = :id"),
        {"id": account.id},
    )
    occurred = row.scalar_one()
    assert occurred == datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
