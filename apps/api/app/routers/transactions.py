import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import Account, Transaction, User
from app.routers.auth import get_current_user
from app.schemas.transactions import (
    ReversalCreate,
    TransactionCreate,
    TransactionOut,
    TransferCreate,
)
from app.services.ledger import (
    DomainConflictError,
    IdempotencyConflictError,
    LedgerError,
    StaleVersionError,
    apply_ledger_movement,
    apply_reversal,
    apply_transfer,
)
from app.services.scheduled import ScheduledError, create_scheduled

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["transactions"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


async def _owned_account(
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> Account:
    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    account_id: uuid.UUID,
    payload: TransactionCreate,
    user: CurrentUser,
    session: DbSession,
) -> TransactionOut:
    await bind_current_user(session, user.id)
    if payload.occurred_at > datetime.now(UTC):
        try:
            scheduled = await create_scheduled(
                session,
                account_id=account_id,
                user_id=user.id,
                idempotency_key=payload.idempotency_key,
                operation_type=payload.operation_type,
                amount_cents=payload.amount_cents,
                occurred_at=payload.occurred_at,
                description=payload.description,
                external_id=payload.external_id,
                fingerprint=payload.fingerprint,
            )
        except ScheduledError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except IdempotencyConflictError:
            raise HTTPException(status_code=409, detail="idempotency key conflict") from None
        await session.commit()
        return TransactionOut(
            id=scheduled.transaction_id,
            kind="credit" if payload.operation_type == "deposit" else "debit",
            operation_type=payload.operation_type,
            status="pending",
            amount_cents=payload.amount_cents,
            occurred_at=payload.occurred_at,
            description=payload.description,
            external_id=payload.external_id,
            fingerprint=payload.fingerprint,
            reversal_of_id=None,
            category_id=None,
            created_at=datetime.now(UTC),
        )
    try:
        result = await apply_ledger_movement(
            session,
            account_id=account_id,
            user_id=user.id,
            idempotency_key=payload.idempotency_key,
            operation_type=payload.operation_type,
            amount_cents=payload.amount_cents,
            occurred_at=payload.occurred_at,
            description=payload.description,
            external_id=payload.external_id,
            fingerprint=payload.fingerprint,
            reverses_transaction_id=None,
        )
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="idempotency key conflict") from None
    except LedgerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    transaction = await session.get(Transaction, result.transaction_id)
    if transaction is None:
        raise HTTPException(status_code=500, detail="transaction missing after ledger")
    out = TransactionOut.model_validate(transaction)
    out.balance_after_cents = result.balance_after_cents
    out.balance_version = result.balance_version
    return out


@router.get("", response_model=list[TransactionOut])
async def list_transactions(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    limit: int = 50,
    offset: int = 0,
) -> list[TransactionOut]:
    await bind_current_user(session, user.id)
    await _owned_account(account_id, user.id, session)
    rows = await session.execute(
        select(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.user_id == user.id,
        )
        .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
        .limit(min(limit, 200))
        .offset(max(offset, 0))
    )
    return [TransactionOut.model_validate(t) for t in rows.scalars()]


@router.post("/transfers", response_model=list[TransactionOut], status_code=201)
async def create_transfer(
    account_id: uuid.UUID,
    payload: TransferCreate,
    user: CurrentUser,
    session: DbSession,
) -> list[TransactionOut]:
    await bind_current_user(session, user.id)
    await _owned_account(account_id, user.id, session)
    try:
        result = await apply_transfer(
            session,
            from_account_id=account_id,
            to_account_id=payload.target_account_id,
            user_id=user.id,
            idempotency_key=payload.idempotency_key,
            amount_cents=payload.amount_cents,
            occurred_at=datetime.now(UTC),
        )
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="idempotency key conflict") from None
    except LedgerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    out = await session.get(Transaction, result.out_transaction_id)
    inn = await session.get(Transaction, result.in_transaction_id)
    if out is None or inn is None:
        raise HTTPException(status_code=500, detail="transfer legs missing")
    return [TransactionOut.model_validate(out), TransactionOut.model_validate(inn)]


@router.post("/{transaction_id}/reversal", response_model=TransactionOut, status_code=201)
async def reverse_transaction(
    account_id: uuid.UUID,
    transaction_id: uuid.UUID,
    payload: ReversalCreate,
    user: CurrentUser,
    session: DbSession,
) -> TransactionOut:
    await bind_current_user(session, user.id)
    await _owned_account(account_id, user.id, session)
    original = await session.get(Transaction, transaction_id)
    if original is None or original.user_id != user.id or original.account_id != account_id:
        raise HTTPException(status_code=404, detail="transaction not found")
    try:
        result = await apply_reversal(
            session,
            account_id=account_id,
            user_id=user.id,
            transaction_id=transaction_id,
            idempotency_key=payload.idempotency_key,
            expected_version=payload.expected_version,
        )
    except StaleVersionError:
        raise HTTPException(status_code=409, detail="stale version, reload and retry") from None
    except DomainConflictError:
        raise HTTPException(status_code=409, detail="transaction already reversed") from None
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="idempotency key conflict") from None
    except LedgerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    transaction = await session.get(Transaction, result.transaction_id)
    if transaction is None:
        raise HTTPException(status_code=500, detail="transaction missing after ledger")
    out = TransactionOut.model_validate(transaction)
    out.balance_after_cents = result.balance_after_cents
    out.balance_version = result.balance_version
    return out
