import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import CardInvoice, CreditCard, InvoicePayment, Transaction, User
from app.routers.auth import get_current_user
from app.services import cards as card_service
from app.services.cards import CHARGE_KINDS, CardError
from app.services.ledger import IdempotencyConflictError, StaleVersionError

router = APIRouter(prefix="/cards", tags=["cards"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


class CardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(pattern="^[A-Z]{3}$")
    limit_cents: int = Field(ge=0)
    closing_day: int = Field(ge=1, le=28)
    due_day: int = Field(ge=1, le=28)
    last_four: str | None = Field(pattern="^[0-9]{4}$", default=None)


class CardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int
    name: str | None = Field(min_length=1, max_length=255, default=None)
    limit_cents: int | None = Field(ge=0, default=None)
    closing_day: int | None = Field(ge=1, le=28, default=None)
    due_day: int | None = Field(ge=1, le=28, default=None)


class CardArchive(BaseModel):
    expected_version: int


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    name: str
    currency: str
    limit_cents: int
    closing_day: int
    due_day: int
    last_four: str | None
    version: int
    archived_at: datetime | None


class ExposureOut(BaseModel):
    exposure_cents: int
    limit_cents: int
    available_cents: int


class PurchaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=100)
    amount_cents: int = Field(gt=0)
    purchase_date: date
    installments: int = Field(ge=1, le=48, default=1)
    description: str | None = Field(min_length=1, max_length=500, default=None)
    category_id: uuid.UUID | None = None
    charge_kind: str = Field(default="purchase")


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    amount_cents: int
    kind: str
    operation_type: str
    status: str
    occurred_at: datetime
    description: str | None
    charge_kind: str | None
    installment_group_id: uuid.UUID | None
    installment_number: int | None
    installment_total: int | None
    result_balance_after_cents: int
    result_balance_version: int


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payer_account_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=100)
    amount_cents: int = Field(gt=0)
    occurred_at: datetime | None = None


class PaymentOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    transaction_id: uuid.UUID
    amount_cents: int
    kind: str
    reversed_by_id: uuid.UUID | None


class PaymentReversalCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)


class InvoiceOut(BaseModel):
    id: uuid.UUID
    card_id: uuid.UUID
    year: int
    month: int
    status: str
    due_date: date | None
    closed_at: datetime | None
    total_cents: int
    paid_cents: int
    remaining_cents: int


def _http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    if message.endswith("not found"):
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=422, detail=message)


def _transaction_out(row: Transaction) -> TransactionOut:
    return TransactionOut(
        id=row.id,
        account_id=row.account_id,
        amount_cents=row.amount_cents,
        kind=row.kind,
        operation_type=row.operation_type,
        status=row.status,
        occurred_at=row.occurred_at,
        description=row.description,
        charge_kind=row.charge_kind,
        installment_group_id=row.installment_group_id,
        installment_number=row.installment_number,
        installment_total=row.installment_total,
        result_balance_after_cents=row.result_balance_after_cents,
        result_balance_version=row.result_balance_version,
    )


def _payment_out(row: InvoicePayment) -> PaymentOut:
    return PaymentOut(
        id=row.id,
        invoice_id=row.invoice_id,
        transaction_id=row.transaction_id,
        amount_cents=row.amount_cents,
        kind=row.kind,
        reversed_by_id=row.reversed_by_id,
    )


async def _invoice_out(session: AsyncSession, invoice: CardInvoice) -> InvoiceOut:
    totals = await card_service.invoice_totals(session, invoice, date.today())
    return InvoiceOut(
        id=invoice.id,
        card_id=invoice.card_id,
        year=invoice.year,
        month=invoice.month,
        status=str(totals["status"]),
        due_date=invoice.due_date,
        closed_at=invoice.closed_at,
        total_cents=int(totals["total_cents"]),
        paid_cents=int(totals["paid_cents"]),
        remaining_cents=int(totals["remaining_cents"]),
    )


async def _owned_invoice(
    session: AsyncSession, invoice_id: uuid.UUID, user_id: uuid.UUID
) -> CardInvoice:
    invoice = await session.get(CardInvoice, invoice_id)
    if invoice is None or invoice.user_id != user_id:
        raise CardError("invoice not found")
    return invoice


@router.post("", response_model=CardOut, status_code=status.HTTP_201_CREATED)
async def create_card_route(payload: CardCreate, user: CurrentUser, session: DbSession) -> CardOut:
    await bind_current_user(session, user.id)
    try:
        card = await card_service.create_card(
            session,
            user_id=user.id,
            name=payload.name,
            currency=payload.currency,
            limit_cents=payload.limit_cents,
            closing_day=payload.closing_day,
            due_day=payload.due_day,
            last_four=payload.last_four,
        )
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return CardOut.model_validate(card)


@router.get("", response_model=list[CardOut])
async def list_cards_route(user: CurrentUser, session: DbSession) -> list[CardOut]:
    await bind_current_user(session, user.id)
    rows = await session.execute(
        select(CreditCard).where(CreditCard.user_id == user.id).order_by(CreditCard.created_at)
    )
    return [CardOut.model_validate(card) for card in rows.scalars().all()]


@router.get("/{card_id}", response_model=CardOut)
async def get_card_route(card_id: uuid.UUID, user: CurrentUser, session: DbSession) -> CardOut:
    await bind_current_user(session, user.id)
    card = await session.get(CreditCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(status_code=404, detail="card not found")
    return CardOut.model_validate(card)


@router.patch("/{card_id}", response_model=CardOut)
async def patch_card_route(
    card_id: uuid.UUID, payload: CardPatch, user: CurrentUser, session: DbSession
) -> CardOut:
    await bind_current_user(session, user.id)
    try:
        card = await card_service.update_card(
            session,
            card_id=card_id,
            user_id=user.id,
            expected_version=payload.expected_version,
            name=payload.name,
            limit_cents=payload.limit_cents,
            closing_day=payload.closing_day,
            due_day=payload.due_day,
        )
    except StaleVersionError:
        raise HTTPException(status_code=409, detail="stale card version") from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return CardOut.model_validate(card)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_card_route(
    card_id: uuid.UUID, payload: CardArchive, user: CurrentUser, session: DbSession
) -> None:
    await bind_current_user(session, user.id)
    try:
        await card_service.archive_card(
            session, card_id=card_id, user_id=user.id, expected_version=payload.expected_version
        )
    except StaleVersionError:
        raise HTTPException(status_code=409, detail="stale card version") from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()


@router.get("/{card_id}/exposure", response_model=ExposureOut)
async def card_exposure_route(
    card_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> ExposureOut:
    await bind_current_user(session, user.id)
    card = await session.get(CreditCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(status_code=404, detail="card not found")
    return ExposureOut(**await card_service.card_exposure(session, card))


@router.post(
    "/{card_id}/purchases", response_model=list[TransactionOut], status_code=status.HTTP_201_CREATED
)
async def create_purchase_route(
    card_id: uuid.UUID, payload: PurchaseCreate, user: CurrentUser, session: DbSession
) -> list[TransactionOut]:
    await bind_current_user(session, user.id)
    if payload.charge_kind not in CHARGE_KINDS:
        raise HTTPException(status_code=422, detail="unsupported charge kind")
    try:
        rows = await card_service.create_card_purchase(
            session,
            card_id=card_id,
            user_id=user.id,
            idempotency_key=payload.idempotency_key,
            amount_cents=payload.amount_cents,
            purchase_date=payload.purchase_date,
            installments=payload.installments,
            description=payload.description,
            category_id=payload.category_id,
            charge_kind=payload.charge_kind,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return [_transaction_out(row) for row in rows]


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def pay_invoice_route(
    invoice_id: uuid.UUID, payload: PaymentCreate, user: CurrentUser, session: DbSession
) -> PaymentOut:
    await bind_current_user(session, user.id)
    try:
        payment = await card_service.apply_invoice_payment(
            session,
            invoice_id=invoice_id,
            user_id=user.id,
            payer_account_id=payload.payer_account_id,
            idempotency_key=payload.idempotency_key,
            amount_cents=payload.amount_cents,
            occurred_at=payload.occurred_at or datetime.now(UTC).replace(microsecond=0),
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return _payment_out(payment)


@router.post(
    "/payments/{payment_id}/reversal",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def reverse_payment_route(
    payment_id: uuid.UUID, payload: PaymentReversalCreate, user: CurrentUser, session: DbSession
) -> PaymentOut:
    await bind_current_user(session, user.id)
    try:
        reversal = await card_service.reverse_invoice_payment(
            session,
            payment_id=payment_id,
            user_id=user.id,
            idempotency_key=payload.idempotency_key,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return _payment_out(reversal)


@router.post(
    "/purchases/{purchase_transaction_id}/reversal",
    response_model=list[TransactionOut],
    status_code=status.HTTP_201_CREATED,
)
async def reverse_purchase_route(
    purchase_transaction_id: uuid.UUID,
    payload: PaymentReversalCreate,
    user: CurrentUser,
    session: DbSession,
) -> list[TransactionOut]:
    await bind_current_user(session, user.id)
    try:
        rows = await card_service.reverse_card_purchase(
            session,
            purchase_transaction_id=purchase_transaction_id,
            user_id=user.id,
            idempotency_key=payload.idempotency_key,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CardError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return [_transaction_out(row) for row in rows]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_invoice_route(
    invoice_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> InvoiceOut:
    await bind_current_user(session, user.id)
    invoice = await _owned_invoice(session, invoice_id, user.id)
    return await _invoice_out(session, invoice)


@router.get("/{card_id}/invoices", response_model=list[InvoiceOut])
async def list_invoices_route(
    card_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[InvoiceOut]:
    await bind_current_user(session, user.id)
    card = await session.get(CreditCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(status_code=404, detail="card not found")
    rows = await session.execute(
        select(CardInvoice)
        .where(CardInvoice.card_id == card_id)
        .order_by(CardInvoice.year, CardInvoice.month)
    )
    return [await _invoice_out(session, invoice) for invoice in rows.scalars().all()]


@router.get("/invoices/{invoice_id}/charges", response_model=list[TransactionOut])
async def invoice_charges_route(
    invoice_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[TransactionOut]:
    await bind_current_user(session, user.id)
    invoice = await _owned_invoice(session, invoice_id, user.id)
    rows = await session.execute(
        select(Transaction)
        .where(
            Transaction.invoice_id == invoice.id,
            Transaction.status == "posted",
            Transaction.operation_type.in_(("card_purchase", "reversal")),
        )
        .order_by(Transaction.occurred_at, Transaction.installment_number)
    )
    return [_transaction_out(row) for row in rows.scalars().all()]


@router.get("/invoices/{invoice_id}/payments", response_model=list[PaymentOut])
async def invoice_payments_route(
    invoice_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[PaymentOut]:
    await bind_current_user(session, user.id)
    invoice = await _owned_invoice(session, invoice_id, user.id)
    rows = await session.execute(
        select(InvoicePayment)
        .where(InvoicePayment.invoice_id == invoice.id)
        .order_by(InvoicePayment.created_at)
    )
    return [_payment_out(row) for row in rows.scalars().all()]
