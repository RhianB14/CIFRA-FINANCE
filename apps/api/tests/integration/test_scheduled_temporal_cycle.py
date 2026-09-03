import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction, User
from app.services.ledger import IdempotencyConflictError
from app.services.scheduled import ScheduledResult, create_scheduled, promote_due


def _future(day: int = 20) -> datetime:
    return (
        (datetime.now(UTC) + timedelta(days=30)).replace(hour=12, minute=0, second=0, microsecond=0)
        if day
        else datetime.now(UTC)
    )


async def _seed(db_session: AsyncSession) -> tuple[User, Account]:
    user = User(
        email=f"ciclo-{uuid.uuid4().hex[:10]}@example.com",
        name="Ciclo",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name="Ciclo A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    return user, account


async def _create(
    db_session: AsyncSession, account: Account, key: str, occurred_at: datetime
) -> ScheduledResult:
    return await create_scheduled(
        db_session,
        account_id=account.id,
        user_id=account.user_id,
        idempotency_key=key,
        operation_type="withdrawal",
        amount_cents=15000,
        occurred_at=occurred_at,
        description="f3 cycle",
    )


@pytest.mark.asyncio
async def test_replay_after_promotion_returns_same_persisted_row(
    db_session: AsyncSession,
) -> None:
    user, account = await _seed(db_session)
    key = f"ciclo-{uuid.uuid4().hex[:10]}"
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    from app.core.db import set_bypass_scope

    await set_bypass_scope(db_session)

    created = await _create(db_session, account, key, occurred_at)
    await db_session.commit()
    assert created.created is True and created.status == "pending"

    first_row = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == created.transaction_id)
        )
    ).scalar_one()
    original_created_at = first_row.created_at
    original_id = first_row.id

    promoted = await promote_due(
        db_session,
        account_id=account.id,
        user_id=user.id,
        today=occurred_at + timedelta(days=1),
    )
    await db_session.commit()
    assert promoted == 1

    from app.services.scheduled import ScheduledError

    replay = None
    scheduled_error = None
    try:
        replay = await _create(db_session, account, key, occurred_at)
    except ScheduledError as exc:
        scheduled_error = exc
    if replay is None:
        pytest.fail(
            f"replay after promotion must return the persisted row, got error: {scheduled_error}"
        )

    await db_session.commit()
    assert replay.created is False
    assert replay.status == "posted"

    row = (
        await db_session.execute(select(Transaction).where(Transaction.id == replay.transaction_id))
    ).scalar_one()
    assert row.id == original_id
    assert row.created_at == original_created_at
    assert row.status == "posted"
    assert row.occurred_at == occurred_at

    count = (
        (
            await db_session.execute(
                select(Transaction).where(
                    Transaction.account_id == account.id,
                    Transaction.idempotency_key == key,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(count) == 1


@pytest.mark.asyncio
async def test_replay_after_promotion_conflicting_payload_is_409_class(
    db_session: AsyncSession,
) -> None:
    user, account = await _seed(db_session)
    key = f"ciclo-b-{uuid.uuid4().hex[:10]}"
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    from app.core.db import set_bypass_scope

    await set_bypass_scope(db_session)

    created = await _create(db_session, account, key, occurred_at)
    await db_session.commit()
    assert created.created is True

    promoted = await promote_due(
        db_session,
        account_id=account.id,
        user_id=user.id,
        today=occurred_at + timedelta(days=1),
    )
    await db_session.commit()
    assert promoted == 1

    from app.services.scheduled import create_scheduled as cs

    with pytest.raises(IdempotencyConflictError):
        await cs(
            db_session,
            account_id=account.id,
            user_id=account.user_id,
            idempotency_key=key,
            operation_type="withdrawal",
            amount_cents=99999,
            occurred_at=occurred_at,
            description="f3 cycle",
        )


@pytest.mark.asyncio
async def test_transaction_create_replay_after_promotion_stable_http(
    tx_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Ciclo HTTP",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    key = f"http-ciclo-{uuid.uuid4().hex[:10]}"
    occurred_at = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    payload = {
        "idempotency_key": key,
        "operation_type": "withdrawal",
        "amount_cents": 20000,
        "occurred_at": occurred_at.isoformat(),
        "description": "f3 replay",
    }
    first = await tx_client.post(f"/accounts/{account_id}/transactions", json=payload)
    assert first.status_code == 201, first.text
    body_first = first.json()
    assert body_first["status"] == "pending"

    from app.core.db import set_bypass_scope
    from app.models import Account

    await set_bypass_scope(db_session)
    owner_row = await db_session.execute(
        select(Account.user_id).where(Account.id == uuid.UUID(account_id))
    )
    owner_id = owner_row.scalar_one()
    promoted = await promote_due(
        db_session,
        account_id=uuid.UUID(account_id),
        user_id=owner_id,
        today=occurred_at + timedelta(days=1),
    )
    await db_session.commit()
    assert promoted == 1

    replay = await tx_client.post(f"/accounts/{account_id}/transactions", json=payload)
    assert replay.status_code == 201, replay.text
    body_replay = replay.json()
    assert body_replay["id"] == body_first["id"]
    assert body_replay["created_at"] == body_first["created_at"]
    assert body_replay["status"] == "posted"
    assert body_replay["occurred_at"] == body_first["occurred_at"]
    assert body_replay["amount_cents"] == body_first["amount_cents"]

    conflict = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={**payload, "amount_cents": 777},
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_replay_after_real_clock_passes_due_date_switches_to_ledger_branch(
    tx_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.db import set_bypass_scope
    from app.routers import transactions as transactions_router
    from app.services.ledger import LedgerResult, apply_ledger_movement
    from app.services.scheduled import ScheduledResult

    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Ciclo Clock",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]
    uuid_account = uuid.UUID(account_id)

    await set_bypass_scope(db_session)
    owner_row = await db_session.execute(select(Account.user_id).where(Account.id == uuid_account))
    owner_id = owner_row.scalar_one()

    t0 = datetime.now(UTC)
    occurred_at = (t0 + timedelta(days=30)).replace(microsecond=0)
    t1 = occurred_at + timedelta(days=1)
    key = f"clock-{uuid.uuid4().hex[:10]}"
    payload = {
        "idempotency_key": key,
        "operation_type": "withdrawal",
        "amount_cents": 20000,
        "occurred_at": occurred_at.isoformat(),
        "description": "f3 clock cycle",
    }

    ledger_calls: list[dict[str, object]] = []

    async def spy_ledger(*args: Any, **kwargs: Any) -> LedgerResult:
        ledger_calls.append(dict(kwargs))
        return await apply_ledger_movement(*args, **kwargs)

    branch_log: list[str] = []

    async def spy_scheduled(*args: Any, **kwargs: Any) -> ScheduledResult:
        branch_log.append("scheduled")
        return await create_scheduled(*args, **kwargs)

    monkeypatch.setattr(transactions_router, "apply_ledger_movement", spy_ledger)
    monkeypatch.setattr(transactions_router, "create_scheduled", spy_scheduled)

    first = await tx_client.post(f"/accounts/{account_id}/transactions", json=payload)
    assert first.status_code == 201, first.text
    body_first = first.json()
    assert body_first["status"] == "pending"
    assert ledger_calls == [], "router must take the scheduled branch before the due date"
    assert branch_log == ["scheduled"]

    class _ShiftedClock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return t1

    monkeypatch.setattr(transactions_router, "datetime", _ShiftedClock)

    promoted = await promote_due(
        db_session,
        account_id=uuid_account,
        user_id=owner_id,
        today=t1,
    )
    await db_session.commit()
    assert promoted == 1

    replay = await tx_client.post(f"/accounts/{account_id}/transactions", json=payload)
    assert replay.status_code == 201, replay.text
    body_replay = replay.json()

    assert len(ledger_calls) == 1, "replay must take the ledger branch after the due date"
    assert branch_log == ["scheduled"], "no second scheduled creation may happen"

    assert body_replay["id"] == body_first["id"]
    assert body_replay["created_at"] == body_first["created_at"]
    assert body_replay["status"] == "posted"
    assert body_replay["occurred_at"] == body_first["occurred_at"]
    assert body_replay["amount_cents"] == body_first["amount_cents"]

    rows = (
        (await db_session.execute(select(Transaction).where(Transaction.idempotency_key == key)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == "posted"

    account_row = await db_session.get(Account, uuid_account)
    assert account_row is not None
    await db_session.refresh(account_row)
    assert account_row.current_balance_cents == 80000
    assert account_row.current_balance_version == 1

    conflict = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={**payload, "amount_cents": 777},
    )
    assert conflict.status_code == 409
