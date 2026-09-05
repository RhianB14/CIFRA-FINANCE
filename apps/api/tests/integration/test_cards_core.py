from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, CardInvoice, Transaction, User
from app.services.cards import (
    apply_invoice_payment,
    close_card_invoices,
    create_card,
    create_card_purchase,
    invoice_totals,
)


async def _user(session: AsyncSession, email: str) -> User:
    user = User(email=email, name="F4", password_hash="hash")
    session.add(user)
    await session.flush()
    return user


async def _account(session: AsyncSession, user: User, cents: int = 100000) -> Account:
    account = Account(
        user_id=user.id,
        name="Conta pagadora",
        kind="checking",
        currency="BRL",
        initial_balance_cents=cents,
        current_balance_cents=cents,
        current_balance_version=0,
    )
    session.add(account)
    await session.flush()
    return account


async def test_purchase_does_not_change_payer_balance_and_materializes_invoice(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session, "card-purchase@example.com")
    payer = await _account(db_session, user)
    card = await create_card(db_session, user.id, "Principal", "BRL", 50000, 25, 10)
    rows = await create_card_purchase(
        db_session,
        card.id,
        user.id,
        "purchase-1",
        12001,
        date(2026, 4, 24),
        1,
        "Mercado",
        None,
        "purchase",
    )
    await db_session.flush()
    await db_session.refresh(payer)
    assert payer.current_balance_cents == 100000
    assert len(rows) == 1
    assert rows[0].invoice_id is not None
    assert rows[0].card_id == card.id
    assert rows[0].amount_cents == 12001
    assert rows[0].kind == "debit"
    assert rows[0].operation_type == "card_purchase"


async def test_installments_are_exact_idempotent_and_land_in_consecutive_invoices(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session, "card-installments@example.com")
    card = await create_card(db_session, user.id, "Viagem", "BRL", 50000, 25, 10)
    first = await create_card_purchase(
        db_session,
        card.id,
        user.id,
        "purchase-installments",
        10001,
        date(2024, 2, 29),
        3,
        "Passagem",
        None,
        "purchase",
    )
    replay = await create_card_purchase(
        db_session,
        card.id,
        user.id,
        "purchase-installments",
        10001,
        date(2024, 2, 29),
        3,
        "Passagem",
        None,
        "purchase",
    )
    assert [row.id for row in replay] == [row.id for row in first]
    assert len(first) == 3
    assert sum(row.amount_cents for row in first) == 10001
    assert [row.installment_number for row in first] == [1, 2, 3]
    assert {row.installment_total for row in first} == {3}
    assert len({row.installment_group_id for row in first}) == 1
    dates = [row.occurred_at.date() for row in first]
    assert dates == [date(2024, 3, 29), date(2024, 4, 29), date(2024, 5, 29)]


async def test_partial_and_total_payment_are_atomic_with_bank_ledger(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session, "card-payment@example.com")
    payer = await _account(db_session, user)
    card = await create_card(db_session, user.id, "Pagamentos", "BRL", 50000, 25, 10)
    rows = await create_card_purchase(
        db_session,
        card.id,
        user.id,
        "payment-purchase",
        10000,
        date(2026, 4, 24),
        1,
        "Compra",
        None,
        "purchase",
    )
    invoice_id = rows[0].invoice_id
    assert invoice_id is not None
    await close_card_invoices(db_session, card, date(2026, 4, 25))
    payment = await apply_invoice_payment(
        db_session,
        invoice_id,
        user.id,
        payer.id,
        "payment-1",
        4000,
        datetime(2026, 5, 1, 12, tzinfo=UTC),
    )
    outbound = await db_session.get(Transaction, payment.transaction_id)
    assert outbound is not None
    assert payment.transaction_id == outbound.id
    assert outbound.operation_type == "card_payment"
    assert outbound.kind.strip() == "debit"
    await db_session.refresh(payer)
    assert payer.current_balance_cents == 96000
    invoice = await db_session.get(CardInvoice, invoice_id)
    assert invoice is not None
    totals = await invoice_totals(db_session, invoice, date(2026, 5, 1))
    assert totals["paid_cents"] == 4000
    assert totals["remaining_cents"] == 6000
    assert totals["status"] == "partially_paid"
    await apply_invoice_payment(
        db_session,
        invoice_id,
        user.id,
        payer.id,
        "payment-2",
        6000,
        datetime(2026, 5, 2, 12, tzinfo=UTC),
    )
    await db_session.refresh(payer)
    assert payer.current_balance_cents == 90000
    assert (
        await db_session.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.operation_type == "card_payment",
                Transaction.account_id == payer.id,
            )
        )
        == 2
    )
