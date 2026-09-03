from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, CardInvoice, CreditCard, Transaction, User
from app.services.cards import (
    CardError,
    apply_invoice_payment,
    close_card_invoices,
    create_card,
    create_card_purchase,
    reverse_card_purchase,
)
from app.services.ledger import IdempotencyConflictError


async def _fixtures(db_session: AsyncSession) -> tuple[User, Account, CreditCard]:
    user = User(email="f4-extra@example.com", name="F4 Extra", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    account = Account(
        user_id=user.id, name="Conta", kind="checking", currency="BRL", current_balance_cents=100000
    )
    db_session.add(account)
    await db_session.flush()
    card = await create_card(db_session, user.id, "Cartao", "BRL", 50000, 25, 10, "4321")
    return user, account, card


async def test_purchase_retry_conflict_and_reversal_idempotency(db_session: AsyncSession) -> None:
    user, _, card = await _fixtures(db_session)
    purchase = await create_card_purchase(
        db_session, card.id, user.id, "key", 10001, date(2024, 2, 29), 3
    )
    replay = await create_card_purchase(
        db_session, card.id, user.id, "key", 10001, date(2024, 2, 29), 3
    )
    assert [item.id for item in replay] == [item.id for item in purchase]
    try:
        await create_card_purchase(db_session, card.id, user.id, "key", 10002, date(2024, 2, 29), 3)
    except IdempotencyConflictError:
        pass
    else:
        raise AssertionError("expected idempotency conflict")
    first = await reverse_card_purchase(db_session, purchase[0].id, user.id, "reverse-key")
    second = await reverse_card_purchase(db_session, purchase[0].id, user.id, "reverse-key")
    assert len(first) == 3
    assert [item.reversal_of_id for item in second] == [item.id for item in purchase]
    assert (
        await db_session.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.reversal_of_id.in_([item.id for item in purchase])
            )
        )
        == 3
    )


async def test_payment_rejects_cross_user_and_overpayment(db_session: AsyncSession) -> None:
    user, account, card = await _fixtures(db_session)
    purchase = await create_card_purchase(
        db_session, card.id, user.id, "purchase", 10000, date(2026, 4, 24), 1
    )
    invoice_id = purchase[0].invoice_id
    assert invoice_id is not None
    invoice = await db_session.get(CardInvoice, invoice_id)
    assert invoice is not None
    invoice.status = "closed"
    other = User(email="other@example.com", name="Outro", password_hash="x")
    db_session.add(other)
    await db_session.flush()
    try:
        await apply_invoice_payment(
            db_session, invoice_id, other.id, account.id, "cross", 1000, datetime.now(UTC)
        )
    except CardError:
        pass
    else:
        raise AssertionError("expected ownership rejection")
    try:
        await apply_invoice_payment(
            db_session, invoice_id, user.id, account.id, "over", 10001, datetime.now(UTC)
        )
    except CardError:
        pass
    else:
        raise AssertionError("expected overpayment rejection")


async def test_closing_rerun_is_idempotent(db_session: AsyncSession) -> None:
    user, _, card = await _fixtures(db_session)
    await create_card_purchase(db_session, card.id, user.id, "purchase", 1000, date(2026, 4, 24), 1)
    assert await close_card_invoices(db_session, card, date(2026, 4, 25)) == 1
    assert await close_card_invoices(db_session, card, date(2026, 4, 25)) == 0
