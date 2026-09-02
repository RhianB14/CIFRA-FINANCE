import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, Transaction, User
from app.services.scheduled import create_scheduled, promote_due

APPEND_ONLY = "transactions is append-only"


async def _make_user_and_account(db_session: AsyncSession) -> Account:
    user = User(
        email=f"sched-{uuid.uuid4().hex[:10]}@example.com",
        name="Sched Flow",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Sched A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return account


async def _insert_pending(db_session: AsyncSession, account: Account) -> uuid.UUID:
    tx = Transaction(
        user_id=account.user_id,
        account_id=account.id,
        idempotency_key=f"sched-{uuid.uuid4().hex[:12]}",
        payload_signature="a" * 64,
        kind="debit",
        operation_type="withdrawal",
        status="pending",
        amount_cents=20000,
        occurred_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
    )
    db_session.add(tx)
    await db_session.commit()
    return tx.id


@pytest.mark.asyncio
async def test_trigger_allows_only_pending_to_posted_transition(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    tx_id = await _insert_pending(db_session, account)

    promoted = cast(
        CursorResult[Any],
        await db_session.execute(
            text("UPDATE transactions SET status = 'posted' WHERE id = :id"),
            {"id": tx_id},
        ),
    )
    assert promoted.rowcount == 1

    with pytest.raises(DBAPIError, match=APPEND_ONLY):
        await db_session.execute(
            text("UPDATE transactions SET status = 'posted' WHERE id = :id"),
            {"id": tx_id},
        )
    await db_session.rollback()

    with pytest.raises(DBAPIError, match=APPEND_ONLY):
        await db_session.execute(
            text("UPDATE transactions SET status = 'pending' WHERE id = :id"),
            {"id": tx_id},
        )
    await db_session.rollback()

    pending_noop = cast(
        CursorResult[Any],
        await db_session.execute(
            text("UPDATE transactions SET status = 'pending' WHERE id = :id"),
            {"id": uuid.uuid4()},
        ),
    )
    assert pending_noop.rowcount == 0


@pytest.mark.asyncio
async def test_trigger_keeps_append_only_on_delete(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    tx_id = await _insert_pending(db_session, account)

    with pytest.raises((DBAPIError, Exception), match="append-only|permission denied"):
        await db_session.execute(
            text("DELETE FROM transactions WHERE id = :id"),
            {"id": tx_id},
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_create_scheduled_keeps_posted_balance_untouched(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)

    sched_key = f"future-{uuid.uuid4().hex[:10]}"
    result = await create_scheduled(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        idempotency_key=sched_key,
        operation_type="withdrawal",
        amount_cents=25000,
        occurred_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        description="aluguel setembro",
    )
    await db_session.commit()

    assert result.status == "pending"
    tx = await db_session.get(Transaction, result.transaction_id)
    assert tx is not None
    assert tx.status == "pending"

    await db_session.refresh(account)
    assert account.current_balance_cents == 100000
    assert account.current_balance_version == 0

    replay = await create_scheduled(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        idempotency_key=sched_key,
        operation_type="withdrawal",
        amount_cents=25000,
        occurred_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        description="aluguel setembro",
    )
    assert replay.transaction_id == result.transaction_id


@pytest.mark.asyncio
async def test_promote_due_posts_once_and_applies_balance_once(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    first_id = await _insert_pending(db_session, account)
    second_id = await _insert_pending(db_session, account)

    before = await promote_due(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        today=datetime(2026, 9, 29, 0, 0, tzinfo=UTC),
    )
    await db_session.commit()
    assert before == 0

    promoted = await promote_due(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        today=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
    )
    await db_session.commit()
    assert promoted == 2

    await db_session.refresh(account)
    assert account.current_balance_cents == 100000 - 40000
    assert account.current_balance_version == 2

    first = await db_session.get(Transaction, first_id)
    second = await db_session.get(Transaction, second_id)
    assert first is not None and second is not None
    assert first.status == "posted"
    assert second.status == "posted"
    assert first.result_balance_after_cents == 80000
    assert second.result_balance_after_cents == 60000
    assert first.result_balance_version == 1
    assert second.result_balance_version == 2

    again = await promote_due(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        today=datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
    )
    await db_session.commit()
    assert again == 0

    await db_session.refresh(account)
    assert account.current_balance_cents == 60000
    assert account.current_balance_version == 2


@pytest.mark.asyncio
async def test_concurrent_promotion_applies_balance_exactly_once(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    await _insert_pending(db_session, account)
    await _insert_pending(db_session, account)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    async def run_promotion(
        session_factory: async_sessionmaker[AsyncSession] = factory,
        acct_id: uuid.UUID = account.id,
        owner_id: uuid.UUID = account.user_id,
    ) -> int:
        async with session_factory() as session:
            await set_bypass_scope(session)
            promoted = await promote_due(
                session,
                account_id=acct_id,
                user_id=owner_id,
                today=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
            )
            await session.commit()
            return promoted

    first, second = await asyncio.gather(run_promotion(), run_promotion())

    async with factory() as session:
        await set_bypass_scope(session)
        row = await session.execute(
            text(
                "SELECT current_balance_cents, current_balance_version FROM accounts WHERE id = :id"
            ),
            {"id": account.id},
        )
        balance, version = row.one()
        assert balance == 100000 - 40000
        assert version == 2
        assert {first, second} == {2, 0}


@pytest.mark.asyncio
async def test_promotion_rejects_foreign_account(
    db_session: AsyncSession,
) -> None:
    account = await _make_user_and_account(db_session)
    await set_bypass_scope(db_session)
    await _insert_pending(db_session, account)

    with pytest.raises(Exception, match="not found"):
        await promote_due(
            db_session,
            account_id=account.id,
            user_id=uuid.uuid4(),
            today=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
        )


async def _second_user_token(http: httpx.AsyncClient) -> str:
    email = f"sched-b-{uuid.uuid4().hex[:10]}@example.com"
    register = await http.post(
        "/auth/register",
        json={"email": email, "name": "Sched B", "password": "Str0ng!Pass123"},
    )
    assert register.status_code in (200, 201), register.text
    login = await http.post("/auth/login", data={"username": email, "password": "Str0ng!Pass123"})
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


@pytest.mark.asyncio
async def test_scheduled_http_flow_keeps_posted_and_projected_distinct(
    tx_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Sched HTTP",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    idempotency_key = f"http-sched-{uuid.uuid4().hex[:10]}"
    future_tx = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": idempotency_key,
            "operation_type": "withdrawal",
            "amount_cents": 25000,
            "occurred_at": "2026-09-30T12:00:00Z",
        },
    )
    assert future_tx.status_code == 201, future_tx.text
    assert future_tx.json()["status"] == "pending"

    before_current = await tx_client.get(f"/accounts/{account_id}/balance")
    assert before_current.status_code == 200
    assert before_current.json() == {
        "account_id": account_id,
        "current_balance_cents": 100000,
        "projected_balance_cents": 100000,
    }
    before_projected = await tx_client.get(f"/accounts/{account_id}/balance?projected=true")
    assert before_projected.json()["current_balance_cents"] == 100000
    assert before_projected.json()["projected_balance_cents"] == 75000

    await set_bypass_scope(db_session)
    owner_row = await db_session.execute(
        text("SELECT user_id FROM accounts WHERE id = :id"),
        {"id": uuid.UUID(account_id)},
    )
    owner_id = owner_row.scalar_one()
    promoted = await promote_due(
        db_session,
        account_id=uuid.UUID(account_id),
        user_id=owner_id,
        today=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
    )
    await db_session.commit()
    assert promoted == 1

    after = await tx_client.get(f"/accounts/{account_id}/balance?projected=true")
    body = after.json()
    assert body["current_balance_cents"] == 75000
    assert body["projected_balance_cents"] == 75000

    listed = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert {t["status"] for t in listed.json()} == {"posted"}

    conflict = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": idempotency_key,
            "operation_type": "withdrawal",
            "amount_cents": 999,
            "occurred_at": "2026-09-30T12:00:00Z",
        },
    )
    assert conflict.status_code == 409

    token_b = await _second_user_token(tx_client)
    foreign = await tx_client.get(
        f"/accounts/{account_id}/balance?projected=true",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert foreign.status_code == 404
