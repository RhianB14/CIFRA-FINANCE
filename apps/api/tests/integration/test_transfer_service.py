import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_two_accounts(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, name, is_active)"
            " VALUES (:id, :email, 'x', 'U', true)"
        ),
        {"id": user_id, "email": f"tr-{user_id}@example.com"},
    )
    account_a = uuid.uuid4()
    account_b = uuid.uuid4()
    for account_id, name in ((account_a, "Conta A"), (account_b, "Conta B")):
        await db_session.execute(
            text(
                "INSERT INTO accounts (id, user_id, name, kind, currency,"
                " initial_balance_cents, current_balance_cents, current_balance_version)"
                " VALUES (:id, :user_id, :name, 'checking', 'BRL',"
                " :initial, :initial, 0)"
            ),
            {"id": account_id, "user_id": user_id, "name": name, "initial": 0},
        )
    await db_session.commit()
    return user_id, account_a, account_b


async def test_transfer_scenario_meets_acceptance_criteria(
    db_session: AsyncSession,
) -> None:
    from app.services.ledger import apply_ledger_movement, apply_transfer

    user_id, account_a, account_b = await _seed_two_accounts(db_session)
    occurred = datetime.now(UTC)

    await apply_ledger_movement(
        db_session,
        account_id=account_a,
        user_id=user_id,
        idempotency_key="salary",
        operation_type="deposit",
        amount_cents=50000,
        occurred_at=occurred,
    )
    await apply_ledger_movement(
        db_session,
        account_id=account_a,
        user_id=user_id,
        idempotency_key="grocery",
        operation_type="withdrawal",
        amount_cents=12000,
        occurred_at=occurred,
    )

    group = await apply_transfer(
        db_session,
        from_account_id=account_a,
        to_account_id=account_b,
        user_id=user_id,
        idempotency_key="transfer-1",
        amount_cents=20000,
        occurred_at=occurred,
    )

    balances = await db_session.execute(
        text("SELECT id, current_balance_cents FROM accounts WHERE id IN (:a, :b) ORDER BY id"),
        {"a": account_a, "b": account_b},
    )
    rows = {str(r["id"]): r["current_balance_cents"] for r in balances.mappings()}
    assert rows[str(account_a)] == 118000
    assert rows[str(account_b)] == 20000

    legs = await db_session.execute(
        text(
            "SELECT operation_type, kind, amount_cents, transfer_group_id"
            " FROM transactions WHERE transfer_group_id = :g ORDER BY operation_type"
        ),
        {"g": group.transfer_group_id},
    )
    leg_rows = legs.mappings().all()
    assert len(leg_rows) == 2
    ops = {r["operation_type"] for r in leg_rows}
    assert ops == {"transfer_in", "transfer_out"}
    assert all(r["amount_cents"] == 20000 for r in leg_rows)


async def test_transfer_replay_does_not_duplicate(db_session: AsyncSession) -> None:
    from app.services.ledger import apply_transfer

    user_id, account_a, account_b = await _seed_two_accounts(db_session)
    occurred = datetime.now(UTC)

    first = await apply_transfer(
        db_session,
        from_account_id=account_a,
        to_account_id=account_b,
        user_id=user_id,
        idempotency_key="tr-key",
        amount_cents=10000,
        occurred_at=occurred,
    )
    replay = await apply_transfer(
        db_session,
        from_account_id=account_a,
        to_account_id=account_b,
        user_id=user_id,
        idempotency_key="tr-key",
        amount_cents=10000,
        occurred_at=occurred,
    )
    assert replay.transfer_group_id == first.transfer_group_id

    count = await db_session.execute(
        text("SELECT count(*) FROM transactions WHERE transfer_group_id = :g"),
        {"g": first.transfer_group_id},
    )
    assert count.scalar_one() == 2

    balance_a = await db_session.execute(
        text("SELECT current_balance_cents FROM accounts WHERE id = :a"),
        {"a": account_a},
    )
    assert balance_a.scalar_one() == 90000


async def test_transfer_rejects_same_account(db_session: AsyncSession) -> None:
    from app.services.ledger import LedgerError, apply_transfer

    user_id, account_a, _ = await _seed_two_accounts(db_session)
    with pytest.raises(LedgerError):
        await apply_transfer(
            db_session,
            from_account_id=account_a,
            to_account_id=account_a,
            user_id=user_id,
            idempotency_key="self",
            amount_cents=100,
            occurred_at=datetime.now(UTC),
        )
