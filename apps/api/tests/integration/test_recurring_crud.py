import uuid
from datetime import date

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import bind_current_user, set_bypass_scope
from app.models import Account, User
from app.services.recurring import RecurringError, create_recurring


async def _make_user_and_account(db_session: AsyncSession) -> Account:
    user = User(
        email=f"rec-{uuid.uuid4().hex[:10]}@example.com",
        name="Rec Flow",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Rec A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=50000,
        current_balance_cents=50000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return account


@pytest.mark.asyncio
async def test_recurring_transactions_have_force_rls(db_session: AsyncSession) -> None:
    for sql, expected in (
        ("SELECT relrowsecurity FROM pg_class WHERE relname = 'recurring_transactions'", True),
        ("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'recurring_transactions'", True),
    ):
        row = await db_session.execute(text(sql))
        assert row.scalar() is expected

    policy = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM pg_policies"
            " WHERE tablename = 'recurring_transactions' AND schemaname = 'public'"
        )
    )
    assert policy.scalar_one() >= 1


@pytest.mark.asyncio
async def test_recurring_rows_are_invisible_across_users(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    created = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="withdrawal",
        template_amount_cents=150000,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
        template_description="aluguel",
    )
    await db_session.commit()

    other = User(
        email=f"rec-b-{uuid.uuid4().hex[:10]}@example.com",
        name="Rec B",
        password_hash="x" * 20,
    )
    db_session.add(other)
    await db_session.commit()

    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        await bind_current_user(session, other.id)
        rows = await session.execute(
            text("SELECT id FROM recurring_transactions WHERE id = :id"),
            {"id": created.id},
        )
        assert rows.scalar_one_or_none() is None

    async with factory() as session:
        await bind_current_user(session, account.user_id)
        rows = await session.execute(
            text("SELECT id FROM recurring_transactions WHERE id = :id"),
            {"id": created.id},
        )
        assert rows.scalar_one_or_none() == created.id


@pytest.mark.asyncio
async def test_create_recurring_rejects_foreign_account(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    with pytest.raises(RecurringError, match="not found"):
        await create_recurring(
            db_session,
            user_id=uuid.uuid4(),
            account_id=account.id,
            template_operation_type="withdrawal",
            template_amount_cents=1000,
            recurrence="monthly",
            starts_on=date(2026, 9, 5),
        )


@pytest.mark.asyncio
async def test_create_recurring_rejects_invalid_cadence(db_session: AsyncSession) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    with pytest.raises(RecurringError, match="cadence"):
        await create_recurring(
            db_session,
            user_id=account.user_id,
            account_id=account.id,
            template_operation_type="withdrawal",
            template_amount_cents=1000,
            recurrence="hourly",
            starts_on=date(2026, 9, 5),
        )


@pytest.mark.asyncio
async def test_create_recurring_sets_next_run_on_to_starts_on(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    created = await create_recurring(
        db_session,
        user_id=account.user_id,
        account_id=account.id,
        template_operation_type="deposit",
        template_amount_cents=500000,
        recurrence="monthly",
        starts_on=date(2026, 9, 5),
    )
    await db_session.commit()
    assert created.next_run_on == date(2026, 9, 5)
    assert created.is_active is True


@pytest.mark.asyncio
async def test_recurring_http_crud_flow(tx_client: httpx.AsyncClient) -> None:
    created_account = await tx_client.post(
        "/accounts",
        json={
            "name": "Rec HTTP",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert created_account.status_code == 201, created_account.text
    account_id = created_account.json()["id"]

    payload = {
        "account_id": account_id,
        "template_operation_type": "withdrawal",
        "template_amount_cents": 150000,
        "recurrence": "monthly",
        "starts_on": "2026-09-05",
        "template_description": "aluguel",
    }
    created = await tx_client.post("/recurring-transactions", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    recurring_id = body["id"]
    assert body["next_run_on"] == "2026-09-05"
    assert body["is_active"] is True
    assert body["recurrence"] == "monthly"

    listed = await tx_client.get("/recurring-transactions")
    assert listed.status_code == 200
    assert any(item["id"] == recurring_id for item in listed.json())

    fetched = await tx_client.get(f"/recurring-transactions/{recurring_id}")
    assert fetched.status_code == 200
    assert fetched.json()["template_amount_cents"] == 150000

    paused = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"is_active": False},
    )
    assert paused.status_code == 200
    assert paused.json()["is_active"] is False

    deleted = await tx_client.delete(f"/recurring-transactions/{recurring_id}")
    assert deleted.status_code == 204

    missing = await tx_client.get(f"/recurring-transactions/{recurring_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_recurring_http_rejects_invalid_payload(tx_client: httpx.AsyncClient) -> None:
    created_account = await tx_client.post(
        "/accounts",
        json={
            "name": "Rec Bad",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    account_id = created_account.json()["id"]

    bad_cadence = await tx_client.post(
        "/recurring-transactions",
        json={
            "account_id": account_id,
            "template_operation_type": "withdrawal",
            "template_amount_cents": 1000,
            "recurrence": "hourly",
            "starts_on": "2026-09-05",
        },
    )
    assert bad_cadence.status_code == 422

    bad_amount = await tx_client.post(
        "/recurring-transactions",
        json={
            "account_id": account_id,
            "template_operation_type": "withdrawal",
            "template_amount_cents": 0,
            "recurrence": "monthly",
            "starts_on": "2026-09-05",
        },
    )
    assert bad_amount.status_code == 422


@pytest.mark.asyncio
async def test_recurring_http_isolated_across_users(tx_client: httpx.AsyncClient) -> None:
    created_account = await tx_client.post(
        "/accounts",
        json={
            "name": "Rec Iso",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    account_id = created_account.json()["id"]
    created = await tx_client.post(
        "/recurring-transactions",
        json={
            "account_id": account_id,
            "template_operation_type": "deposit",
            "template_amount_cents": 70000,
            "recurrence": "weekly",
            "starts_on": "2026-09-07",
        },
    )
    assert created.status_code == 201
    recurring_id = created.json()["id"]

    email = f"rec-x-{uuid.uuid4().hex[:10]}@example.com"
    register = await tx_client.post(
        "/auth/register",
        json={"email": email, "name": "Rec X", "password": "Str0ng!Pass123"},
    )
    assert register.status_code in (200, 201)
    login = await tx_client.post(
        "/auth/login", data={"username": email, "password": "Str0ng!Pass123"}
    )
    token_b = str(login.json()["access_token"])

    foreign_get = await tx_client.get(
        f"/recurring-transactions/{recurring_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert foreign_get.status_code == 404

    foreign_delete = await tx_client.delete(
        f"/recurring-transactions/{recurring_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert foreign_delete.status_code == 404
