import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import (
    Account,
    AccountBalanceSnapshot,
    ImportBatch,
    Transaction,
    User,
)
from app.routers.auth import get_current_user
from app.schemas.accounts import AccountCreate, AccountOut, AccountUpdate, account_to_out
from app.schemas.balance import AccountBalanceOut
from app.schemas.imports import ImportBatchOut, SnapshotCreate, SnapshotOut
from app.services.csv_import import ImportError_, import_csv

router = APIRouter(prefix="/accounts", tags=["accounts"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{account_id}/balance", response_model=AccountBalanceOut)
async def account_balance(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    projected: bool = False,
) -> AccountBalanceOut:
    await bind_current_user(session, user.id)
    account = await _owned_account(account_id, user.id, session)
    current = account.current_balance_cents
    pending = 0
    if projected:
        from sqlalchemy import func

        row = await session.execute(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.status == "pending",
            )
        )
        raw = int(row.scalar_one())
        debits = await session.execute(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == account_id,
                Transaction.status == "pending",
                Transaction.kind == "debit",
            )
        )
        pending = raw - 2 * int(debits.scalar_one())
    return AccountBalanceOut(
        account_id=str(account_id),
        current_balance_cents=current,
        projected_balance_cents=current + pending,
    )


@router.post("/{account_id}/imports", response_model=ImportBatchOut, status_code=201)
async def import_account_csv(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    source_name: Annotated[str, Form(...)],
) -> ImportBatchOut:
    await bind_current_user(session, user.id)
    await _owned_account(account_id, user.id, session)
    content = await file.read()
    try:
        result = await import_csv(
            session,
            account_id=account_id,
            user_id=user.id,
            source_name=source_name,
            file_name=file.filename or "upload.csv",
            content=content,
        )
    except ImportError_ as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    batch = await session.get(ImportBatch, result.batch_id)
    if batch is None:
        raise HTTPException(status_code=500, detail="import batch missing")
    return ImportBatchOut(
        id=batch.id,
        account_id=batch.account_id,
        source_name=batch.source_name,
        file_name=batch.file_name,
        file_sha256=batch.file_sha256,
        row_count=result.row_count,
        imported_count=result.imported_count,
        skipped_count=result.skipped_count,
        created_at=batch.created_at,
    )


@router.post("/{account_id}/snapshots", response_model=SnapshotOut, status_code=201)
async def create_snapshot(
    account_id: uuid.UUID,
    payload: SnapshotCreate,
    user: CurrentUser,
    session: DbSession,
) -> SnapshotOut:
    await bind_current_user(session, user.id)
    account = await _owned_account(account_id, user.id, session)
    ledger_balance = account.current_balance_cents
    reported = payload.reported_balance_cents
    difference = reported - ledger_balance
    snapshot = AccountBalanceSnapshot(
        user_id=user.id,
        account_id=account_id,
        reported_balance_cents=reported,
        ledger_balance_cents=ledger_balance,
        difference_cents=difference,
        status="matched" if difference == 0 else "divergent",
        note=payload.note,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return SnapshotOut.model_validate(snapshot)


@router.get("/{account_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[SnapshotOut]:
    await bind_current_user(session, user.id)
    await _owned_account(account_id, user.id, session)
    rows = await session.execute(
        select(AccountBalanceSnapshot)
        .where(AccountBalanceSnapshot.account_id == account_id)
        .order_by(AccountBalanceSnapshot.created_at.desc())
    )
    return [SnapshotOut.model_validate(s) for s in rows.scalars()]


async def _owned_account(
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> Account:
    account = await session.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    user: CurrentUser,
    session: DbSession,
) -> AccountOut:
    await bind_current_user(session, user.id)
    account = Account(
        user_id=user.id,
        name=payload.name,
        kind=payload.kind,
        currency=payload.currency.upper(),
        initial_balance_cents=payload.initial_balance_cents,
        current_balance_cents=payload.initial_balance_cents,
        current_balance_version=0,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account_to_out(account)


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    user: CurrentUser,
    session: DbSession,
) -> list[AccountOut]:
    await bind_current_user(session, user.id)
    rows = await session.execute(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at)
    )
    return [account_to_out(account) for account in rows.scalars()]


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> AccountOut:
    await bind_current_user(session, user.id)
    account = await _owned_account(account_id, user.id, session)
    return account_to_out(account)


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    user: CurrentUser,
    session: DbSession,
) -> AccountOut:
    await bind_current_user(session, user.id)
    account = await _owned_account(account_id, user.id, session)
    if (
        payload.expected_version is not None
        and payload.expected_version != account.current_balance_version
    ):
        raise HTTPException(status_code=409, detail="stale version, reload and retry")
    if payload.name is not None:
        account.name = payload.name
    if payload.kind is not None:
        account.kind = payload.kind
    if payload.archived is not None:
        from datetime import UTC, datetime

        account.archived_at = datetime.now(UTC) if payload.archived else None
    await session.commit()
    await session.refresh(account)
    return account_to_out(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    await bind_current_user(session, user.id)
    account = await _owned_account(account_id, user.id, session)
    await session.delete(account)
    await session.commit()
