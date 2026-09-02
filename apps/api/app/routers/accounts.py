import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import Account, User
from app.routers.auth import get_current_user
from app.schemas.accounts import AccountCreate, AccountOut, AccountUpdate, account_to_out

router = APIRouter(prefix="/accounts", tags=["accounts"])

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
