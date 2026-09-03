import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_bypass_scope
from app.models import Account, RecurringTransaction, Transaction, User
from app.services.csv_import import ImportError_
from app.services.csv_import import import_csv as csv_import
from app.services.dashboard import (
    DashboardError,
    dashboard_evolution,
    dashboard_month_comparison,
    dashboard_summary,
    month_range,
    parse_month,
    previous_month,
)
from app.services.recurring import (
    RecurringError,
    advance_date,
    create_recurring,
    delete_recurring,
    get_recurring,
    update_recurring,
)
from app.services.scheduled import ScheduledError, create_scheduled

LF = chr(10)
HEADER = "occurred_at,amount_cents,kind,external_id"
HDRD = HEADER + ",description"


def csv_bytes(*lines: str) -> bytes:
    return (LF.join(lines) + LF).encode("utf-8")


async def _user_with_account(session: AsyncSession, currency: str = "BRL") -> tuple[User, Account]:
    await set_bypass_scope(session)
    user = User(
        email=f"cov-{uuid.uuid4().hex[:8]}@example.com",
        name="Cov",
        locale="pt-BR",
        password_hash="x",
        totp_enabled=False,
    )
    session.add(user)
    await session.flush()
    account = Account(
        user_id=user.id,
        name="Cov acct",
        kind="checking",
        currency=currency,
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    session.add(account)
    await session.flush()
    return user, account


def test_parse_month_validations() -> None:
    assert parse_month(None) == datetime.now(UTC).strftime("%Y-%m")
    assert parse_month("2026-02") == "2026-02"
    for bad in ("2026-2", "26-02", "2026-13", "not-a-month"):
        with pytest.raises(DashboardError):
            parse_month(bad)


def test_month_helpers() -> None:
    assert previous_month("2026-01") == "2025-12"
    assert month_range("2026-03", 3) == ["2026-01", "2026-02", "2026-03"]


def test_advance_date_validations() -> None:
    assert advance_date(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert advance_date(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)
    with pytest.raises(RecurringError):
        advance_date(date(2026, 9, 2), "monthly", -1)
    with pytest.raises(RecurringError):
        advance_date(date(2026, 9, 2), "decade", 1)


@pytest.mark.asyncio
async def test_create_recurring_validations(db_session: AsyncSession) -> None:
    user, account = await _user_with_account(db_session)
    with pytest.raises(RecurringError):
        await create_recurring(
            db_session, user.id, account.id, "deposit", 100, "decade", date(2026, 9, 1)
        )
    with pytest.raises(RecurringError):
        await create_recurring(
            db_session, user.id, account.id, "transfer", 100, "monthly", date(2026, 9, 1)
        )
    with pytest.raises(RecurringError):
        await create_recurring(
            db_session, user.id, account.id, "deposit", 0, "monthly", date(2026, 9, 1)
        )
    with pytest.raises(RecurringError):
        await create_recurring(
            db_session,
            user.id,
            account.id,
            "deposit",
            100,
            "monthly",
            date(2026, 9, 1),
            ends_on=date(2026, 8, 31),
        )
    with pytest.raises(RecurringError):
        await create_recurring(
            db_session, user.id, uuid.uuid4(), "deposit", 100, "monthly", date(2026, 9, 1)
        )


@pytest.mark.asyncio
async def test_recurring_crud_error_paths(db_session: AsyncSession) -> None:
    user, account = await _user_with_account(db_session)
    created = await create_recurring(
        db_session,
        user.id,
        account.id,
        "deposit",
        500,
        "monthly",
        date(2026, 9, 5),
        template_description="aluguel",
    )
    with pytest.raises(RecurringError):
        await get_recurring(db_session, user.id, uuid.uuid4())
    with pytest.raises(RecurringError):
        await update_recurring(db_session, user.id, uuid.uuid4(), {"is_active": False})
    with pytest.raises(RecurringError):
        await update_recurring(db_session, user.id, created.id, {"template_amount_cents": 1})
    inactive = await update_recurring(
        db_session, user.id, created.id, {"ends_on": date(2027, 9, 1), "is_active": False}
    )
    assert inactive.is_active is False
    with pytest.raises(RecurringError):
        await update_recurring(db_session, user.id, created.id, {"ends_on": date(2026, 8, 1)})
    reactivated = await update_recurring(
        db_session,
        user.id,
        created.id,
        {"is_active": True, "ends_on": date(2027, 8, 1)},
    )
    assert reactivated.is_active is True
    assert reactivated.ends_on == date(2027, 8, 1)
    await delete_recurring(db_session, user.id, created.id)
    await db_session.flush()
    with pytest.raises(RecurringError):
        await delete_recurring(db_session, user.id, created.id)
    negative = await create_recurring(
        db_session,
        user.id,
        account.id,
        "deposit",
        300,
        "monthly",
        date(2026, 10, 5),
    )
    with pytest.raises(RecurringError):
        await update_recurring(db_session, user.id, negative.id, {"ends_on": date(2026, 8, 1)})


@pytest.mark.asyncio
async def test_create_scheduled_validations(db_session: AsyncSession) -> None:
    user, account = await _user_with_account(db_session)
    future = datetime.now(UTC) + timedelta(days=2)
    with pytest.raises(ScheduledError):
        await create_scheduled(
            db_session,
            account.id,
            user.id,
            f"cov-{uuid.uuid4().hex[:8]}",
            "deposit",
            0,
            future,
        )
    with pytest.raises(ScheduledError):
        await create_scheduled(
            db_session,
            account.id,
            user.id,
            f"cov-{uuid.uuid4().hex[:8]}",
            "transfer",
            100,
            future,
        )
    with pytest.raises(ScheduledError):
        await create_scheduled(
            db_session,
            account.id,
            user.id,
            f"cov-{uuid.uuid4().hex[:8]}",
            "deposit",
            100,
            datetime.now(UTC) - timedelta(days=2),
        )
    with pytest.raises(ScheduledError):
        await create_scheduled(
            db_session,
            uuid.uuid4(),
            user.id,
            f"cov-{uuid.uuid4().hex[:8]}",
            "deposit",
            100,
            future,
        )


@pytest.mark.asyncio
async def test_csv_import_error_paths(db_session: AsyncSession) -> None:
    user, account = await _user_with_account(db_session)
    with pytest.raises(ImportError_):
        await csv_import(
            db_session,
            account.id,
            user.id,
            "bad.csv",
            "bad.csv",
            csv_bytes("timestamp,value", "2026-01-05,100"),
        )
    with pytest.raises(ImportError_):
        await csv_import(
            db_session,
            account.id,
            user.id,
            "bad.csv",
            "bad.csv",
            csv_bytes(HEADER, "not-a-date,100,credit,ext1"),
        )
    with pytest.raises(ImportError_):
        await csv_import(
            db_session,
            account.id,
            user.id,
            "bad.csv",
            "bad.csv",
            csv_bytes(HEADER, "2026-01-05,notanumber,credit,ext1"),
        )
    with pytest.raises(ImportError_):
        await csv_import(
            db_session,
            account.id,
            user.id,
            "bad.csv",
            "bad.csv",
            csv_bytes(HEADER, "2026-01-05,100,side,ext1"),
        )
    with pytest.raises(ImportError_):
        await csv_import(
            db_session,
            account.id,
            user.id,
            "long.csv",
            "long.csv",
            csv_bytes(HEADER, "2026-01-05,100,credit," + "x" * 256),
        )


@pytest.mark.asyncio
async def test_dashboard_services_direct(db_session: AsyncSession) -> None:
    user, account = await _user_with_account(db_session)
    await set_bypass_scope(db_session)
    account.current_balance_cents = 50000
    now = datetime.now(UTC)
    month = now.strftime("%Y-%m")
    year_i, month_i = int(month[:4]), int(month[5:7])
    in_month = datetime(year_i, month_i, 5, 12, 0, tzinfo=UTC)
    late_month = datetime(year_i, month_i, 20, 12, 0, tzinfo=UTC)
    rows = [
        Transaction(
            user_id=user.id,
            account_id=account.id,
            idempotency_key=f"cov-{uuid.uuid4().hex[:10]}",
            payload_signature="sig",
            kind="credit",
            operation_type="deposit",
            status="posted",
            amount_cents=90000,
            occurred_at=in_month,
            result_balance_after_cents=90000,
            result_balance_version=1,
        ),
        Transaction(
            user_id=user.id,
            account_id=account.id,
            idempotency_key=f"cov-{uuid.uuid4().hex[:10]}",
            payload_signature="sig",
            kind="debit",
            operation_type="withdrawal",
            status="posted",
            amount_cents=40000,
            occurred_at=late_month,
            result_balance_after_cents=50000,
            result_balance_version=2,
        ),
        Transaction(
            user_id=user.id,
            account_id=account.id,
            idempotency_key=f"cov-{uuid.uuid4().hex[:10]}",
            payload_signature="sig",
            kind="debit",
            operation_type="withdrawal",
            status="pending",
            amount_cents=7500,
            occurred_at=now + timedelta(days=10),
            result_balance_after_cents=0,
            result_balance_version=0,
        ),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.flush()

    summary = await dashboard_summary(db_session, user.id, month)
    assert summary.month == month
    assert summary.consolidated_by_currency[0].currency == "BRL"
    assert summary.consolidated_by_currency[0].posted_balance_cents == 50000
    assert summary.consolidated_by_currency[0].projected_balance_cents == 42500
    assert summary.month_flow[0].income_cents == 90000
    assert summary.month_flow[0].expense_cents == 40000
    assert len(summary.upcoming) == 1
    assert len(summary.recent) == 2
    assert summary.accounts[0].projected_balance_cents == 42500

    points = await dashboard_evolution(db_session, user.id, 4, month)
    assert len(points) == 4
    assert points[-1].end_balance_cents == 50000

    comparison = await dashboard_month_comparison(db_session, user.id, month)
    assert comparison.current_month == month
    assert comparison.rows[0].current_net_cents == 50000


@pytest.mark.asyncio
async def test_materialize_conflicting_preexisting_key(db_session: AsyncSession) -> None:
    from app.services.ledger import IdempotencyConflictError
    from app.services.recurring import materialize_recurring

    user, account = await _user_with_account(db_session)
    await set_bypass_scope(db_session)
    recurring = RecurringTransaction(
        user_id=user.id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=500,
        template_description=None,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
        ends_on=None,
        next_run_on=date(2026, 9, 5),
        is_active=True,
    )
    db_session.add(recurring)
    await db_session.flush()
    stale = Transaction(
        user_id=user.id,
        account_id=account.id,
        idempotency_key=f"recurring:{recurring.id}:2026-09-05",
        payload_signature="tampered",
        kind="credit",
        operation_type="deposit",
        status="posted",
        amount_cents=999,
        occurred_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        result_balance_after_cents=0,
        result_balance_version=0,
    )
    db_session.add(stale)
    await db_session.flush()
    with pytest.raises(IdempotencyConflictError):
        await materialize_recurring(db_session, user.id, date(2026, 9, 10))
