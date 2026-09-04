from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import (
    Account,
    CardInvoice,
    Category,
    CreditCard,
    InvoicePayment,
    Transaction,
    User,
)
from app.services.cards import (
    CardError,
    apply_invoice_payment,
    card_exposure,
    create_card,
    create_card_purchase,
    invoice_due_date,
    invoice_totals,
    reverse_card_purchase,
    reverse_invoice_payment,
)


async def _setup(session: AsyncSession) -> tuple[User, Account, CreditCard]:
    user = User(email=f"{uuid4().hex}@example.com", name="T", password_hash="x")
    session.add(user)
    await session.flush()
    payer = Account(
        user_id=user.id,
        name="Conta",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    session.add(payer)
    await session.flush()
    card = await create_card(session, user.id, "Cartao", "BRL", 100000, 25, 10, "4321")
    return user, payer, card


async def _purchase(
    session: AsyncSession,
    user: User,
    card: CreditCard,
    key: str,
    amount: int = 10000,
    installments: int = 1,
) -> list[Transaction]:
    return await create_card_purchase(
        session, card.id, user.id, key, amount, date(2026, 4, 24), installments, "Compra"
    )


async def _invoice(
    session: AsyncSession, card: CreditCard, year: int = 2026, month: int = 4
) -> CardInvoice:
    rows = await session.execute(
        sa.select(CardInvoice).where(
            CardInvoice.card_id == card.id, CardInvoice.year == year, CardInvoice.month == month
        )
    )
    return rows.scalar_one()


T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def test_payment_reversal_is_append_only_and_replayable(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    payment = await apply_invoice_payment(
        db_session, invoice.id, user.id, payer.id, "pay-1", 4000, T0
    )
    reversal = await reverse_invoice_payment(db_session, payment.id, user.id, "rev-1")
    assert reversal.kind == "reversal"
    assert reversal.reversed_by_id == payment.id
    assert reversal.amount_cents == payment.amount_cents
    rerun = await reverse_invoice_payment(db_session, payment.id, user.id, "rev-1")
    assert rerun.id == reversal.id
    count = await db_session.scalar(sa.select(sa.func.count()).select_from(InvoicePayment))
    assert count == 2
    totals = await invoice_totals(db_session, invoice, T0.date())
    assert totals["paid_cents"] == 0


async def test_payment_replay_ignores_server_timestamp(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    first = await apply_invoice_payment(
        db_session, invoice.id, user.id, payer.id, "pay-1", 4000, T0
    )
    balance_after_first = payer.current_balance_cents
    replay = await apply_invoice_payment(
        db_session,
        invoice.id,
        user.id,
        payer.id,
        "pay-1",
        4000,
        T0.replace(hour=13),
    )
    assert replay.id == first.id
    assert payer.current_balance_cents == balance_after_first


async def test_payer_cannot_be_card_companion_account(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    with pytest.raises(CardError):
        await apply_invoice_payment(
            db_session, invoice.id, user.id, card.account_id, "pay-1", 4000, T0
        )


async def test_purchase_on_closed_invoice_is_rejected(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    invoice.status = "closed"
    invoice.closed_at = T0
    invoice.version += 1
    await db_session.flush()
    with pytest.raises(CardError):
        await _purchase(db_session, user, card, "p2")


async def test_purchase_validates_category_ownership(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    other = User(email=f"{uuid4().hex}@example.com", name="O", password_hash="x")
    db_session.add(other)
    await db_session.flush()
    foreign = Category(user_id=other.id, name="Alheia", kind="expense")
    db_session.add(foreign)
    await db_session.flush()
    with pytest.raises(CardError):
        await create_card_purchase(
            db_session,
            card.id,
            user.id,
            "p1",
            5000,
            date(2026, 4, 24),
            1,
            "Compra",
            category_id=foreign.id,
        )
    with pytest.raises(CardError):
        await create_card_purchase(
            db_session,
            card.id,
            user.id,
            "p2",
            5000,
            date(2026, 4, 24),
            1,
            "Compra",
            category_id=uuid4(),
        )


async def test_same_idempotency_key_across_users_is_independent(db_session: AsyncSession) -> None:
    user_a, _payer_a, card_a = await _setup(db_session)
    user_b = User(email=f"{uuid4().hex}@example.com", name="B", password_hash="x")
    db_session.add(user_b)
    await db_session.flush()
    payer_b = Account(
        user_id=user_b.id,
        name="Conta B",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(payer_b)
    await db_session.flush()
    card_b = await create_card(db_session, user_b.id, "Cartao B", "BRL", 100000, 25, 10)
    first_a = await _purchase(db_session, user_a, card_a, "shared-key", 9000, 3)
    replay_a = await _purchase(db_session, user_a, card_a, "shared-key", 9000, 3)
    assert [row.id for row in replay_a] == [row.id for row in first_a]
    created_b = await _purchase(db_session, user_b, card_b, "shared-key", 9000, 3)
    assert len(created_b) == 3
    replay_b = await _purchase(db_session, user_b, card_b, "shared-key", 9000, 3)
    assert {row.account_id for row in replay_b} == {card_b.account_id}
    reversals_b = await reverse_card_purchase(db_session, created_b[0].id, user_b.id, "rev-b")
    assert len(reversals_b) == 3
    assert {row.account_id for row in reversals_b} == {card_b.account_id}
    a_reversed = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(Transaction)
        .where(Transaction.reversal_of_id.in_([row.id for row in first_a]))
    )
    assert a_reversed == 0
    exposure_a = await card_exposure(db_session, card_a)
    assert exposure_a["exposure_cents"] == 9000


async def test_invoice_status_is_persisted_on_payment(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    await apply_invoice_payment(db_session, invoice.id, user.id, payer.id, "pay-1", 4000, T0)
    await db_session.refresh(invoice)
    assert invoice.status == "partially_paid"
    await apply_invoice_payment(db_session, invoice.id, user.id, payer.id, "pay-2", 6000, T0)
    await db_session.refresh(invoice)
    assert invoice.status == "paid"


async def test_invoice_status_is_restored_after_payment_reversal(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    payment = await apply_invoice_payment(
        db_session, invoice.id, user.id, payer.id, "pay-1", 10000, T0
    )
    await db_session.refresh(invoice)
    assert invoice.status == "paid"
    await reverse_invoice_payment(db_session, payment.id, user.id, "rev-1")
    await db_session.refresh(invoice)
    assert invoice.status == "overdue"


async def test_invoice_due_date_is_snapshotted_on_creation(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    assert invoice.due_date == invoice_due_date(2026, 4, card.due_day)


async def test_concurrent_payments_cannot_exceed_invoice_total(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    state = (user.id, payer.id, invoice.id)

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def pay(session_index: int) -> InvoicePayment:
        async with factory() as scope:
            from app.core.db import set_bypass_scope

            await set_bypass_scope(scope)
            uid, pid, iid = state
            result = await apply_invoice_payment(
                scope,
                iid,
                uid,
                pid,
                f"race-{session_index}",
                6000,
                T0,
            )
            await scope.commit()
            return result

    results = []
    errors = []
    for index in (1, 2):
        try:
            results.append(await pay(index))
        except CardError as exc:
            errors.append(exc)
    assert len(results) == 1
    assert len(errors) == 1
    async with factory() as check:
        from app.core.db import set_bypass_scope

        await set_bypass_scope(check)
        paid = await check.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(InvoicePayment.amount_cents), 0)).where(
                InvoicePayment.kind == "payment"
            )
        )
        assert paid == 6000


async def test_installment_and_linkage_check_constraints(db_session: AsyncSession) -> None:
    user, payer, card = await _setup(db_session)
    await db_session.commit()
    card_id = card.id
    base = {
        "user_id": user.id,
        "account_id": card.account_id,
        "idempotency_key": "bad-1",
        "payload_signature": "0" * 64,
        "kind": "debit",
        "operation_type": "card_purchase",
        "status": "posted",
        "amount_cents": 100,
        "occurred_at": T0,
        "result_balance_after_cents": 0,
        "result_balance_version": 0,
    }
    with pytest.raises(sa.exc.IntegrityError):
        db_session.add(Transaction(**{**base, "card_id": None, "invoice_id": None}))
        await db_session.flush()
    await db_session.rollback()
    with pytest.raises(sa.exc.IntegrityError):
        db_session.add(
            Transaction(
                **{
                    **base,
                    "idempotency_key": "bad-2",
                    "card_id": card_id,
                    "invoice_id": uuid4(),
                    "installment_number": 2,
                    "installment_total": 1,
                }
            )
        )
        await db_session.flush()
    await db_session.rollback()
