import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, User
from app.services.ledger import apply_transfer


def occurred() -> datetime:
    return datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_transfer_locks_are_acquired_one_by_one_in_canonical_order(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    user = User(
        email=f"lockorder-{uuid.uuid4().hex[:10]}@example.com",
        name="Lock Order",
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    first = Account(
        user_id=user.id,
        name="Lock A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=70000,
        current_balance_cents=70000,
        current_balance_version=0,
    )
    second = Account(
        user_id=user.id,
        name="Lock B",
        kind="checking",
        currency="BRL",
        initial_balance_cents=30000,
        current_balance_cents=30000,
        current_balance_version=0,
    )
    db_session.add(first)
    db_session.add(second)
    await db_session.commit()

    canonical_first, canonical_second = sorted((first.id, second.id))
    captured: list[tuple[str, Any]] = []

    def _capture(
        _conn: object,
        _cursor: object,
        statement: str,
        parameters: Any,
        _context: object,
        _executemany: bool,
    ) -> None:
        captured.append((statement, parameters))

    event.listen(migrated_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
        async with factory() as session:
            await set_bypass_scope(session)
            await apply_transfer(
                session,
                from_account_id=first.id,
                to_account_id=second.id,
                user_id=user.id,
                idempotency_key=f"lock-order-{uuid.uuid4().hex[:8]}",
                amount_cents=10000,
                occurred_at=occurred(),
            )
            await session.commit()
    finally:
        event.remove(migrated_engine.sync_engine, "before_cursor_execute", _capture)

    lock_statements = [
        (statement, parameters) for statement, parameters in captured if "FOR UPDATE" in statement
    ]
    assert len(lock_statements) == 2, captured
    for statement, _parameters in lock_statements:
        assert " IN (" not in statement, statement
    locked_sequence = [str(parameters[0]) for _statement, parameters in lock_statements]
    assert locked_sequence == [str(canonical_first), str(canonical_second)], captured
