import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import User
from app.routers.auth import get_current_user
from app.services.recurring import (
    RecurringError,
    create_recurring,
    delete_recurring,
    get_recurring,
    list_recurring,
    update_recurring,
)

router = APIRouter(prefix="/recurring-transactions", tags=["recurring-transactions"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


class RecurringCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    template_operation_type: str = Field(pattern="^(deposit|withdrawal)$")
    template_amount_cents: int = Field(gt=0)
    recurrence: str = Field(pattern="^(daily|weekly|monthly|yearly)$")
    starts_on: date
    ends_on: date | None = None
    template_description: str | None = Field(min_length=1, max_length=500, default=None)


class RecurringPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_description: str | None = Field(min_length=1, max_length=500, default=None)
    ends_on: date | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _reject_null_is_active(self) -> "RecurringPatch":
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null: omit the field or send true/false")
        return self

    def updates(self) -> dict[str, object]:
        fields_set = self.model_fields_set
        updates: dict[str, object] = {}
        if "template_description" in fields_set:
            updates["template_description"] = self.template_description
        if "ends_on" in fields_set:
            updates["ends_on"] = self.ends_on
        if "is_active" in fields_set:
            updates["is_active"] = self.is_active
        return updates


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    template_operation_type: str
    template_amount_cents: int
    template_description: str | None
    recurrence: str
    starts_on: date
    ends_on: date | None
    next_run_on: date
    is_active: bool


def _http_error(exc: RecurringError) -> HTTPException:
    message = str(exc)
    if message.endswith("not found"):
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.post("", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
async def create_recurring_route(
    payload: RecurringCreate,
    user: CurrentUser,
    session: DbSession,
) -> RecurringOut:
    await bind_current_user(session, user.id)
    try:
        created = await create_recurring(
            session,
            user_id=user.id,
            account_id=payload.account_id,
            template_operation_type=payload.template_operation_type,
            template_amount_cents=payload.template_amount_cents,
            recurrence=payload.recurrence,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            template_description=payload.template_description,
        )
    except RecurringError as exc:
        raise _http_error(exc) from None
    await session.commit()
    row = await get_recurring(session, user.id, created.id)
    return RecurringOut(
        id=row.id,
        account_id=row.account_id,
        template_operation_type=payload.template_operation_type,
        template_amount_cents=payload.template_amount_cents,
        template_description=payload.template_description,
        recurrence=row.recurrence,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        next_run_on=row.next_run_on,
        is_active=row.is_active,
    )


@router.get("", response_model=list[RecurringOut])
async def list_recurring_route(user: CurrentUser, session: DbSession) -> list[RecurringOut]:
    await bind_current_user(session, user.id)
    rows = await list_recurring(session, user.id)
    return [
        RecurringOut(
            id=row.id,
            account_id=row.account_id,
            template_operation_type=row.template_operation_type,
            template_amount_cents=row.template_amount_cents,
            template_description=row.template_description,
            recurrence=row.recurrence,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            next_run_on=row.next_run_on,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.get("/{recurring_id}", response_model=RecurringOut)
async def get_recurring_route(
    recurring_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> RecurringOut:
    await bind_current_user(session, user.id)
    try:
        row = await get_recurring(session, user.id, recurring_id)
    except RecurringError as exc:
        raise _http_error(exc) from None
    return RecurringOut(
        id=row.id,
        account_id=row.account_id,
        template_operation_type=str(getattr(row, "template_operation_type", "")),
        template_amount_cents=int(getattr(row, "template_amount_cents", 0)),
        template_description=getattr(row, "template_description", None),
        recurrence=row.recurrence,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        next_run_on=row.next_run_on,
        is_active=row.is_active,
    )


@router.patch("/{recurring_id}", response_model=RecurringOut)
async def patch_recurring_route(
    recurring_id: uuid.UUID,
    payload: RecurringPatch,
    user: CurrentUser,
    session: DbSession,
) -> RecurringOut:
    await bind_current_user(session, user.id)
    updates = payload.updates()
    try:
        row = await update_recurring(session, user.id, recurring_id, updates)
    except RecurringError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return RecurringOut(
        id=row.id,
        account_id=row.account_id,
        template_operation_type=str(getattr(row, "template_operation_type", "")),
        template_amount_cents=int(getattr(row, "template_amount_cents", 0)),
        template_description=getattr(row, "template_description", None),
        recurrence=row.recurrence,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        next_run_on=row.next_run_on,
        is_active=row.is_active,
    )


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring_route(
    recurring_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await bind_current_user(session, user.id)
    try:
        await delete_recurring(session, user.id, recurring_id)
    except RecurringError as exc:
        raise _http_error(exc) from None
    await session.commit()
