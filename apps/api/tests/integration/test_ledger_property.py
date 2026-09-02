import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ledger import apply_ledger_movement

money = st.integers(min_value=1, max_value=10**9)
kind = st.sampled_from(["credit", "debit"])
keys = st.text(alphabet="abcdefghijkmnopqrstuvwxyz0123456789-", min_size=6, max_size=24)


@pytest.fixture
async def prop_session(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    yield db_session


@settings(
    max_examples=500, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(amount=money, kind=kind)
@pytest.mark.asyncio
async def test_balance_invariant_holds_for_arbitrary_movements(
    prop_session: AsyncSession,
    amount: int,
    kind: str,
) -> None:
    from app.models import Account, User

    user = User(email=f"hyp-{uuid.uuid4().hex[:10]}@example.com", name="H", password_hash="x")
    prop_session.add(user)
    await prop_session.commit()
    account = Account(
        user_id=user.id,
        name="H-Acc",
        kind="checking",
        currency="BRL",
        current_balance_cents=0,
    )
    prop_session.add(account)
    await prop_session.commit()

    await apply_ledger_movement(
        prop_session,
        account_id=account.id,
        user_id=user.id,
        idempotency_key=f"hyp-{uuid.uuid4().hex[:12]}",
        operation_type="deposit" if kind == "credit" else "withdrawal",
        amount_cents=amount,
        occurred_at=datetime.now(UTC),
    )
    await prop_session.commit()

    refreshed = await prop_session.get(Account, account.id)
    assert refreshed is not None
    expected = amount if kind == "credit" else -amount
    assert refreshed.current_balance_cents == expected
