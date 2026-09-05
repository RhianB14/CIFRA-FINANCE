import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.models import Account, CardInvoice, Category, CreditCard, InvoicePayment, Transaction
from app.services.ledger import (
    IdempotencyConflictError,
    StaleVersionError,
    payload_signature,
)

CHARGE_KINDS = ("purchase", "interest", "late_fee", "iof", "withdrawal_fee", "other")
MAX_INSTALLMENTS = 48


class CardError(Exception):
    pass


async def _refresh_locked(session: AsyncSession, obj: object) -> None:
    attributes.instance_state(obj)
    await session.refresh(obj, with_for_update=True)


async def _lock_finite(session: AsyncSession, account_ids: set[UUID]) -> None:
    ordered = sorted(account_ids)
    rows = await session.execute(
        select(Account.id).where(Account.id.in_(ordered)).order_by(Account.id).with_for_update()
    )
    locked = list(rows.scalars().all())
    if len(locked) != len(ordered):
        missing = set(ordered) - set(locked)
        raise CardError(f"account not found: {sorted(missing)[0]}")


@dataclass(frozen=True, slots=True)
class InstallmentPlan:
    periods: list[tuple[int, int]]
    amounts: list[int]


def add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + offset
    return total // 12, total % 12 + 1


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def invoice_period_for_purchase(purchase_date: date, closing_day: int) -> tuple[int, int]:
    if purchase_date.day <= closing_day:
        return purchase_date.year, purchase_date.month
    return add_months(purchase_date.year, purchase_date.month, 1)


def invoice_due_date(year: int, month: int, due_day: int) -> date:
    due_year, due_month = add_months(year, month, 1)
    return date(due_year, due_month, min(due_day, days_in_month(due_year, due_month)))


def occurred_at_for_period(year: int, month: int, purchase_date: date) -> datetime:
    day = min(purchase_date.day, days_in_month(year, month))
    return datetime(year, month, day, 12, 0, 0, tzinfo=UTC)


def build_installment_plan(
    purchase_date: date,
    closing_day: int,
    total_cents: int,
    installments: int,
) -> InstallmentPlan:
    if not 1 <= installments <= MAX_INSTALLMENTS:
        raise ValueError("installments must be between 1 and 48")
    if total_cents < installments:
        raise ValueError("total_cents must allocate at least one cent per installment")
    base_year, base_month = invoice_period_for_purchase(purchase_date, closing_day)
    periods = [add_months(base_year, base_month, i) for i in range(installments)]
    base_amount = total_cents // installments
    remainder = total_cents % installments
    amounts = [base_amount + (1 if i < remainder else 0) for i in range(installments)]
    return InstallmentPlan(periods=periods, amounts=amounts)


def derive_invoice_status(
    invoice: CardInvoice,
    total_cents: int,
    paid_cents: int,
    today: date,
) -> str:
    if total_cents > 0 and paid_cents >= total_cents:
        return "paid"
    if total_cents > 0 and 0 < paid_cents < total_cents:
        return "partially_paid"
    if invoice.status == "open":
        return "open"
    return "closed"


async def _owned_card(session: AsyncSession, card_id: UUID, user_id: UUID) -> CreditCard:
    card = await session.get(CreditCard, card_id)
    if card is None or card.user_id != user_id:
        raise CardError("card not found")
    await _refresh_locked(session, card)
    return card


async def get_or_create_invoice(
    session: AsyncSession,
    card: CreditCard,
    year: int,
    month: int,
) -> CardInvoice:
    stmt = (
        pg_insert(CardInvoice)
        .values(
            user_id=card.user_id,
            card_id=card.id,
            year=year,
            month=month,
            status="open",
            due_date=invoice_due_date(year, month, card.due_day),
        )
        .on_conflict_do_nothing(index_elements=["card_id", "year", "month"])
        .returning(CardInvoice.id)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is not None:
        invoice = await session.get(CardInvoice, row.id)
        assert invoice is not None
        return invoice
    existing = await session.execute(
        select(CardInvoice).where(
            CardInvoice.card_id == card.id,
            CardInvoice.year == year,
            CardInvoice.month == month,
        )
    )
    return existing.scalar_one()


async def create_card(
    session: AsyncSession,
    user_id: UUID,
    name: str,
    currency: str,
    limit_cents: int,
    closing_day: int,
    due_day: int,
    last_four: str | None = None,
) -> CreditCard:
    if limit_cents < 0:
        raise CardError("limit must be non-negative")
    if not 1 <= closing_day <= 28 or not 1 <= due_day <= 28:
        raise CardError("closing_day and due_day must be between 1 and 28")
    if len(currency) != 3 or not currency.isalpha() or not currency.isupper():
        raise CardError("currency must be a 3-letter uppercase code")
    if last_four is not None and (len(last_four) != 4 or not last_four.isdigit()):
        raise CardError("last_four must be exactly 4 digits")
    duplicate = await session.execute(
        select(CreditCard).where(CreditCard.user_id == user_id, CreditCard.name == name)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise CardError("card name already exists for user")
    companion = Account(
        user_id=user_id,
        name=f"Cartao {name}",
        kind="credit",
        currency=currency,
        initial_balance_cents=0,
        current_balance_cents=0,
        current_balance_version=0,
    )
    session.add(companion)
    await session.flush()
    card = CreditCard(
        user_id=user_id,
        account_id=companion.id,
        name=name,
        currency=currency,
        limit_cents=limit_cents,
        closing_day=closing_day,
        due_day=due_day,
        last_four=last_four,
    )
    session.add(card)
    await session.flush()
    return card


async def update_card(
    session: AsyncSession,
    card_id: UUID,
    user_id: UUID,
    expected_version: int,
    name: str | None = None,
    limit_cents: int | None = None,
    closing_day: int | None = None,
    due_day: int | None = None,
) -> CreditCard:
    card = await _owned_card(session, card_id, user_id)
    if card.version != expected_version:
        raise StaleVersionError("stale card version")
    if closing_day is not None and not 1 <= closing_day <= 28:
        raise CardError("closing_day must be between 1 and 28")
    if due_day is not None and not 1 <= due_day <= 28:
        raise CardError("due_day must be between 1 and 28")
    if limit_cents is not None and limit_cents < 0:
        raise CardError("limit must be non-negative")
    if name is not None and name != card.name:
        duplicate = await session.execute(
            select(CreditCard).where(CreditCard.user_id == user_id, CreditCard.name == name)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise CardError("card name already exists for user")
    result = await session.execute(
        sa.update(CreditCard)
        .where(CreditCard.id == card_id, CreditCard.version == expected_version)
        .values(
            **{
                k: v
                for k, v in {
                    "name": name,
                    "limit_cents": limit_cents,
                    "closing_day": closing_day,
                    "due_day": due_day,
                    "version": card.version + 1,
                }.items()
                if v is not None
            }
        )
        .returning(CreditCard.id)
    )
    if result.first() is None:
        raise StaleVersionError("stale card version")
    await session.refresh(card)
    return card


async def archive_card(
    session: AsyncSession,
    card_id: UUID,
    user_id: UUID,
    expected_version: int,
) -> CreditCard:
    card = await _owned_card(session, card_id, user_id)
    if card.version != expected_version:
        raise StaleVersionError("stale card version")
    result = await session.execute(
        sa.update(CreditCard)
        .where(CreditCard.id == card_id, CreditCard.version == expected_version)
        .values(archived_at=datetime.now(UTC), version=card.version + 1)
        .returning(CreditCard.id)
    )
    if result.first() is None:
        raise StaleVersionError("stale card version")
    await session.refresh(card)
    return card


async def card_exposure(session: AsyncSession, card: CreditCard) -> dict[str, int]:
    rows = await session.execute(
        select(
            Transaction.kind,
            sa.func.sum(Transaction.amount_cents),
        )
        .where(
            Transaction.account_id == card.account_id,
            Transaction.status == "posted",
            Transaction.operation_type.in_(("card_purchase", "card_payment", "reversal")),
        )
        .group_by(Transaction.kind)
    )
    net = 0
    for kind, amount in rows.all():
        net += -int(amount) if str(kind).strip() == "debit" else int(amount)
    exposure = -net
    return {
        "exposure_cents": exposure,
        "limit_cents": card.limit_cents,
        "available_cents": card.limit_cents - exposure,
    }


def _installment_keys(base: str, installments: int) -> list[str]:
    if installments == 1:
        return [base]
    return [f"{base}#{i + 1}" for i in range(installments)]


def _group_seed(secret_seed: str) -> UUID:
    return uuid.uuid5(NAMESPACE_GROUP, secret_seed)


async def create_card_purchase(
    session: AsyncSession,
    card_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    amount_cents: int,
    purchase_date: date,
    installments: int,
    description: str | None = None,
    category_id: UUID | None = None,
    charge_kind: str = "purchase",
) -> list[Transaction]:
    if charge_kind not in CHARGE_KINDS:
        raise CardError("unsupported charge kind")
    if amount_cents <= 0:
        raise CardError("amount must be positive")
    if category_id is not None:
        category = await session.get(Category, category_id)
        if category is None or category.user_id != user_id:
            raise CardError("category not found")
    if not 1 <= installments <= MAX_INSTALLMENTS:
        raise CardError(f"installments must be between 1 and {MAX_INSTALLMENTS}")
    if charge_kind != "purchase" and installments > 1:
        raise CardError("fees and charges cannot be installment-split")
    card = await _owned_card(session, card_id, user_id)
    if card.archived_at is not None:
        raise CardError("card is archived")

    keys = _installment_keys(idempotency_key, installments)
    existing_first = await session.execute(
        select(Transaction).where(
            Transaction.account_id == card.account_id,
            Transaction.idempotency_key == keys[0],
        )
    )
    anchor = existing_first.scalar_one_or_none()
    if anchor is not None:
        group_rows = await session.execute(
            select(Transaction)
            .where(Transaction.installment_group_id == anchor.installment_group_id)
            .order_by(Transaction.installment_number)
        )
        group = list(group_rows.scalars().all()) if anchor.installment_group_id else [anchor]
        if (
            len(group) != installments
            or [row.amount_cents for row in group]
            != build_installment_plan(
                purchase_date, card.closing_day, amount_cents, installments
            ).amounts
        ):
            raise IdempotencyConflictError("idempotency key conflict")
        return group

    await _lock_finite(session, {card.account_id})
    account = await session.get(Account, card.account_id)
    assert account is not None
    await _refresh_locked(session, account)
    plan = build_installment_plan(purchase_date, card.closing_day, amount_cents, installments)
    group_id = _group_seed(f"inst:{user_id}:{card.id}:{idempotency_key}")
    created: list[Transaction] = []
    for index, (year, month) in enumerate(plan.periods):
        invoice = await get_or_create_invoice(session, card, year, month)
        if invoice.status != "open":
            raise CardError("invoice period is already closed")
        installment_amount = plan.amounts[index]
        occurred_at = occurred_at_for_period(year, month, purchase_date)
        signature = payload_signature(
            "card_purchase",
            installment_amount,
            occurred_at,
            description,
            None,
            None,
            None,
        )
        account.current_balance_cents -= installment_amount
        account.current_balance_version += 1
        multi = installments > 1
        txn = Transaction(
            user_id=user_id,
            account_id=card.account_id,
            idempotency_key=keys[index],
            payload_signature=signature,
            kind="debit",
            operation_type="card_purchase",
            status="posted",
            amount_cents=installment_amount,
            occurred_at=occurred_at,
            description=description,
            category_id=category_id,
            card_id=card.id,
            invoice_id=invoice.id,
            charge_kind=charge_kind,
            installment_group_id=group_id if multi else None,
            installment_number=index + 1 if multi else None,
            installment_total=installments if multi else None,
            result_balance_after_cents=account.current_balance_cents,
            result_balance_version=account.current_balance_version,
        )
        session.add(txn)
        created.append(txn)
    await session.flush()
    return created


T0_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NAMESPACE_GROUP = uuid.UUID("6f1c42f6-0f3e-5a44-9a17-2c6b8d3e5a10")


async def apply_invoice_payment(
    session: AsyncSession,
    invoice_id: UUID,
    user_id: UUID,
    payer_account_id: UUID,
    idempotency_key: str,
    amount_cents: int,
    occurred_at: datetime,
) -> InvoicePayment:
    if amount_cents <= 0:
        raise CardError("payment amount must be positive")

    invoice = await session.get(CardInvoice, invoice_id)
    if invoice is None or invoice.user_id != user_id:
        raise CardError("invoice not found")
    card = await session.get(CreditCard, invoice.card_id)
    assert card is not None
    payer = await session.get(Account, payer_account_id)
    if payer is None or payer.user_id != user_id:
        raise CardError("payer account not found")
    if payer.id == card.account_id:
        raise CardError("payer must differ from the card companion account")
    if payer.currency != card.currency:
        raise CardError("payer account currency must match card currency")

    card = await session.get(CreditCard, invoice.card_id)
    assert card is not None
    await _refresh_locked(session, card)
    await _lock_finite(session, {payer.id, card.account_id})
    payer = await session.get(Account, payer_account_id)
    assert payer is not None
    await _refresh_locked(session, payer)
    card_acct = await session.get(Account, card.account_id)
    assert card_acct is not None
    await _refresh_locked(session, card_acct)
    locked_invoice = await session.execute(
        select(CardInvoice).where(CardInvoice.id == invoice.id).with_for_update()
    )
    if locked_invoice.scalar_one() is None:
        raise CardError("invoice not found")
    await session.refresh(invoice)

    signature = payload_signature(
        "card_payment",
        amount_cents,
        T0_EPOCH,
        str(invoice_id),
        None,
        None,
        None,
    )
    existing = await session.execute(
        select(InvoicePayment).where(
            InvoicePayment.account_id == payer_account_id,
            InvoicePayment.idempotency_key == idempotency_key,
        )
    )
    previous = existing.scalar_one_or_none()
    if previous is not None:
        if previous.payload_signature != signature or previous.invoice_id != invoice.id:
            raise IdempotencyConflictError("idempotency key conflict")
        return previous

    total = await _invoice_charges_total(session, invoice.id)
    paid = await _invoice_paid_total(session, invoice.id)
    if amount_cents > total - paid:
        raise CardError("payment exceeds remaining invoice balance")

    group_id = _group_seed(f"pay:{user_id}:{invoice_id}:{idempotency_key}")
    payer.current_balance_cents -= amount_cents
    payer.current_balance_version += 1
    out_txn = Transaction(
        user_id=user_id,
        account_id=payer_account_id,
        idempotency_key=idempotency_key,
        payload_signature=signature,
        kind="debit",
        operation_type="card_payment",
        status="posted",
        amount_cents=amount_cents,
        occurred_at=occurred_at,
        description=f"Invoice {invoice.year}-{invoice.month:02d}",
        card_id=card.id,
        invoice_id=invoice.id,
        charge_kind="payment",
        transfer_group_id=group_id,
        result_balance_after_cents=payer.current_balance_cents,
        result_balance_version=payer.current_balance_version,
    )
    session.add(out_txn)

    card_acct = await session.get(Account, card.account_id)
    assert card_acct is not None
    card_acct.current_balance_cents += amount_cents
    card_acct.current_balance_version += 1
    card_txn = Transaction(
        user_id=user_id,
        account_id=card.account_id,
        idempotency_key=f"{idempotency_key}:card",
        payload_signature=signature,
        kind="credit",
        operation_type="card_payment",
        status="posted",
        amount_cents=amount_cents,
        occurred_at=occurred_at,
        description=f"Invoice {invoice.year}-{invoice.month:02d}",
        card_id=card.id,
        invoice_id=invoice.id,
        charge_kind="payment",
        transfer_group_id=group_id,
        result_balance_after_cents=card_acct.current_balance_cents,
        result_balance_version=card_acct.current_balance_version,
    )
    session.add(card_txn)
    await session.flush()

    payment = InvoicePayment(
        user_id=user_id,
        invoice_id=invoice.id,
        account_id=payer_account_id,
        transaction_id=out_txn.id,
        idempotency_key=idempotency_key,
        payload_signature=signature,
        amount_cents=amount_cents,
        kind="payment",
    )
    session.add(payment)
    await session.flush()
    totals = await invoice_totals(session, invoice, occurred_at.date())
    await session.execute(
        sa.update(CardInvoice)
        .where(CardInvoice.id == invoice.id, CardInvoice.version == invoice.version)
        .values(status=str(totals["status"]), version=invoice.version + 1)
    )
    await session.refresh(invoice)
    return payment


async def _invoice_charges_total(session: AsyncSession, invoice_id: UUID) -> int:
    rows = await session.execute(
        select(
            Transaction.kind,
            sa.func.sum(Transaction.amount_cents),
        )
        .where(
            Transaction.invoice_id == invoice_id,
            Transaction.status == "posted",
            Transaction.operation_type.in_(("card_purchase", "reversal")),
        )
        .group_by(Transaction.kind)
    )
    total = 0
    for kind, amount in rows.all():
        total += -int(amount) if str(kind).strip() == "credit" else int(amount)
    return total


async def _invoice_paid_total(session: AsyncSession, invoice_id: UUID) -> int:
    rows = await session.execute(
        select(InvoicePayment.kind, sa.func.sum(InvoicePayment.amount_cents))
        .where(InvoicePayment.invoice_id == invoice_id)
        .group_by(InvoicePayment.kind)
    )
    paid = 0
    for kind, amount in rows.all():
        paid += -int(amount) if str(kind).strip() == "reversal" else int(amount)
    return paid


def apply_overdue_rule(status: str, invoice: CardInvoice, today: date) -> str:
    if (
        status in ("closed", "partially_paid")
        and invoice.due_date is not None
        and today > invoice.due_date
    ):
        return "overdue"
    return status


async def invoice_totals(
    session: AsyncSession,
    invoice: CardInvoice,
    today: date,
) -> dict[str, int | str]:
    total = await _invoice_charges_total(session, invoice.id)
    paid = await _invoice_paid_total(session, invoice.id)
    status = derive_invoice_status(invoice, total, paid, today)
    status = apply_overdue_rule(status, invoice, today)
    return {
        "total_cents": total,
        "paid_cents": paid,
        "remaining_cents": max(total - paid, 0),
        "status": status,
    }


async def reverse_card_purchase(
    session: AsyncSession,
    purchase_transaction_id: UUID,
    user_id: UUID,
    idempotency_key: str,
) -> list[Transaction]:
    rows = await session.execute(
        select(Transaction).where(
            Transaction.id == purchase_transaction_id,
            Transaction.user_id == user_id,
            Transaction.operation_type == "card_purchase",
        )
    )
    anchor = rows.scalar_one_or_none()
    if anchor is None:
        raise CardError("purchase not found")
    if anchor.installment_group_id is not None:
        group_rows = await session.execute(
            select(Transaction)
            .where(
                Transaction.installment_group_id == anchor.installment_group_id,
                Transaction.operation_type == "card_purchase",
            )
            .order_by(Transaction.installment_number)
        )
        targets = list(group_rows.scalars().all())
    else:
        targets = [anchor]

    if anchor.card_id is not None:
        card_row = await session.get(CreditCard, anchor.card_id)
        assert card_row is not None
        await _refresh_locked(session, card_row)
    await _lock_finite(session, {target.account_id for target in targets})

    reversal_keys = [
        idempotency_key if len(targets) == 1 else f"{idempotency_key}#{target.installment_number}"
        for target in targets
    ]
    existing = await session.execute(
        select(Transaction).where(
            Transaction.account_id == anchor.account_id,
            Transaction.idempotency_key.in_(reversal_keys),
        )
    )
    prior = list(existing.scalars().all())
    if prior:
        if len(prior) == len(targets) and {row.reversal_of_id for row in prior} == {
            target.id for target in targets
        }:
            return prior
        raise IdempotencyConflictError("idempotency key conflict")

    reversals: list[Transaction] = []
    occurred_at = datetime.now(UTC).replace(microsecond=0)
    for target in targets:
        already = await session.execute(
            select(sa.func.count())
            .select_from(Transaction)
            .where(Transaction.reversal_of_id == target.id)
        )
        if (already.scalar_one() or 0) > 0:
            continue
        account = await session.get(Account, target.account_id)
        assert account is not None
        await _refresh_locked(session, account)
        account.current_balance_cents += target.amount_cents
        account.current_balance_version += 1
        reversal_key = (
            idempotency_key
            if len(targets) == 1
            else f"{idempotency_key}#{target.installment_number}"
        )
        signature = payload_signature(
            "reversal",
            target.amount_cents,
            occurred_at,
            None,
            None,
            None,
            target.id,
        )
        reversal = Transaction(
            user_id=user_id,
            account_id=target.account_id,
            idempotency_key=reversal_key,
            payload_signature=signature,
            kind="credit",
            operation_type="reversal",
            status="posted",
            amount_cents=target.amount_cents,
            occurred_at=occurred_at,
            description=target.description,
            card_id=target.card_id,
            invoice_id=target.invoice_id,
            charge_kind=target.charge_kind,
            installment_group_id=target.installment_group_id,
            installment_number=target.installment_number,
            installment_total=target.installment_total,
            reversal_of_id=target.id,
            result_balance_after_cents=account.current_balance_cents,
            result_balance_version=account.current_balance_version,
        )
        session.add(reversal)
        reversals.append(reversal)
    await session.flush()
    if anchor.invoice_id is not None:
        invoice = await session.get(CardInvoice, anchor.invoice_id)
        if invoice is not None:
            totals = await invoice_totals(session, invoice, occurred_at.date())
            await session.execute(
                sa.update(CardInvoice)
                .where(CardInvoice.id == invoice.id)
                .values(status=str(totals["status"]))
            )
    return reversals


async def reverse_invoice_payment(
    session: AsyncSession,
    payment_id: UUID,
    user_id: UUID,
    idempotency_key: str,
) -> InvoicePayment:
    rows = await session.execute(
        select(InvoicePayment).where(
            InvoicePayment.id == payment_id,
            InvoicePayment.user_id == user_id,
        )
    )
    payment = rows.scalar_one_or_none()
    if payment is None or payment.kind != "payment":
        raise CardError("payment not found")

    await _refresh_locked(session, payment)
    existing = await session.execute(
        select(InvoicePayment).where(InvoicePayment.reversed_by_id == payment_id)
    )
    claimed = existing.scalar_one_or_none()
    if claimed is not None:
        if claimed.idempotency_key == idempotency_key:
            return claimed
        raise CardError("payment already reversed")
    prior_key = await session.execute(
        select(InvoicePayment).where(
            InvoicePayment.account_id == payment.account_id,
            InvoicePayment.idempotency_key == idempotency_key,
        )
    )
    if prior_key.scalar_one_or_none() is not None:
        raise IdempotencyConflictError("idempotency key conflict")

    invoice = await session.get(CardInvoice, payment.invoice_id)
    assert invoice is not None
    card = await session.get(CreditCard, invoice.card_id)
    assert card is not None
    await _refresh_locked(session, card)
    await _lock_finite(session, {payment.account_id, card.account_id})
    payer = await session.get(Account, payment.account_id)
    assert payer is not None
    await _refresh_locked(session, payer)
    locked_invoice = await session.execute(
        select(CardInvoice).where(CardInvoice.id == invoice.id).with_for_update()
    )
    if locked_invoice.scalar_one() is None:
        raise CardError("invoice not found")
    await session.refresh(invoice)
    occurred_at = datetime.now(UTC).replace(microsecond=0)
    signature = payload_signature(
        "card_payment_reversal",
        payment.amount_cents,
        occurred_at,
        str(payment.invoice_id),
        None,
        None,
        None,
    )

    payer.current_balance_cents += payment.amount_cents
    payer.current_balance_version += 1
    in_txn = Transaction(
        user_id=user_id,
        account_id=payment.account_id,
        idempotency_key=idempotency_key,
        payload_signature=signature,
        kind="credit",
        operation_type="card_payment",
        status="posted",
        amount_cents=payment.amount_cents,
        occurred_at=occurred_at,
        description=f"Reversal of invoice payment {invoice.year}-{invoice.month:02d}",
        card_id=card.id,
        invoice_id=invoice.id,
        charge_kind="payment_reversal",
        transfer_group_id=_group_seed(f"rev:{idempotency_key}"),
        result_balance_after_cents=payer.current_balance_cents,
        result_balance_version=payer.current_balance_version,
    )
    session.add(in_txn)

    card_acct = await session.get(Account, card.account_id)
    assert card_acct is not None
    card_acct.current_balance_cents -= payment.amount_cents
    card_acct.current_balance_version += 1
    card_txn = Transaction(
        user_id=user_id,
        account_id=card.account_id,
        idempotency_key=f"{idempotency_key}:card",
        payload_signature=signature,
        kind="debit",
        operation_type="card_payment",
        status="posted",
        amount_cents=payment.amount_cents,
        occurred_at=occurred_at,
        description=f"Reversal of invoice payment {invoice.year}-{invoice.month:02d}",
        card_id=card.id,
        invoice_id=invoice.id,
        charge_kind="payment_reversal",
        transfer_group_id=_group_seed(f"rev:{idempotency_key}"),
        result_balance_after_cents=card_acct.current_balance_cents,
        result_balance_version=card_acct.current_balance_version,
    )
    session.add(card_txn)
    await session.flush()

    reversal = InvoicePayment(
        user_id=user_id,
        invoice_id=invoice.id,
        account_id=payment.account_id,
        transaction_id=in_txn.id,
        idempotency_key=idempotency_key,
        payload_signature=signature,
        amount_cents=payment.amount_cents,
        kind="reversal",
        reversed_by_id=payment.id,
    )
    session.add(reversal)
    await session.flush()
    totals = await invoice_totals(session, invoice, occurred_at.date())
    await session.execute(
        sa.update(CardInvoice)
        .where(CardInvoice.id == invoice.id, CardInvoice.version == invoice.version)
        .values(status=str(totals["status"]), version=invoice.version + 1)
    )
    await session.refresh(invoice)
    return reversal


async def close_card_invoices(session: AsyncSession, card: CreditCard, today: date) -> int:
    changes = 0
    rows = await session.execute(
        select(CardInvoice).where(
            CardInvoice.card_id == card.id,
            CardInvoice.status.in_(("open", "closed", "partially_paid")),
        )
    )
    for invoice in rows.scalars().all():
        if invoice.status == "open":
            closing = date(invoice.year, invoice.month, card.closing_day)
            if today >= closing:
                claim = await session.execute(
                    sa.update(CardInvoice)
                    .where(
                        CardInvoice.id == invoice.id,
                        CardInvoice.status == "open",
                        CardInvoice.version == invoice.version,
                    )
                    .values(
                        status="closed",
                        closed_at=datetime.now(UTC),
                        due_date=invoice_due_date(invoice.year, invoice.month, card.due_day),
                        version=invoice.version + 1,
                    )
                    .returning(CardInvoice.id)
                )
                if claim.first() is not None:
                    changes += 1
                    session.expire(invoice)
        else:
            totals = await invoice_totals(session, invoice, today)
            new_status = str(totals["status"])
            if new_status != invoice.status:
                refreshed = await session.execute(
                    sa.update(CardInvoice)
                    .where(
                        CardInvoice.id == invoice.id,
                        CardInvoice.version == invoice.version,
                    )
                    .values(status=new_status, version=invoice.version + 1)
                    .returning(CardInvoice.id)
                )
                if refreshed.first() is not None:
                    changes += 1
                    session.expire(invoice)
    await session.flush()
    return changes
