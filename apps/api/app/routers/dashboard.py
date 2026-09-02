import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_current_user, get_session
from app.models import User
from app.routers.auth import get_current_user
from app.services.dashboard import (
    DashboardError,
    dashboard_evolution,
    dashboard_month_comparison,
    dashboard_summary,
    parse_month,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


class CurrencyBalanceOut(BaseModel):
    currency: str
    posted_balance_cents: int
    projected_balance_cents: int


class AccountBalanceOut(BaseModel):
    account_id: uuid.UUID
    name: str
    currency: str
    kind: str
    posted_balance_cents: int
    projected_balance_cents: int


class MonthFlowOut(BaseModel):
    currency: str
    month: str
    income_cents: int
    expense_cents: int
    net_cents: int


class UpcomingOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    operation_type: str
    status: str
    amount_cents: int
    occurred_at: str
    description: str | None


class RecentOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    operation_type: str
    status: str
    amount_cents: int
    occurred_at: str
    description: str | None


class SummaryOut(BaseModel):
    month: str
    consolidated_by_currency: list[CurrencyBalanceOut]
    month_flow: list[MonthFlowOut]
    accounts: list[AccountBalanceOut]
    upcoming: list[UpcomingOut]
    recent: list[RecentOut]


class EvolutionOut(BaseModel):
    currency: str
    month: str
    income_cents: int
    expense_cents: int
    end_balance_cents: int


class ComparisonRowOut(BaseModel):
    currency: str
    current_income_cents: int
    current_expense_cents: int
    current_net_cents: int
    previous_income_cents: int
    previous_expense_cents: int
    previous_net_cents: int
    delta_income_cents: int
    delta_expense_cents: int
    delta_net_cents: int


class ComparisonOut(BaseModel):
    current_month: str
    previous_month: str
    rows: list[ComparisonRowOut]


def _iso(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.get("/summary", response_model=SummaryOut)
async def summary_route(
    user: CurrentUser,
    session: DbSession,
    month: str | None = Query(default=None),
) -> SummaryOut:
    await bind_current_user(session, user.id)
    try:
        normalized = parse_month(month)
        data = await dashboard_summary(session, user.id, normalized)
    except DashboardError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return SummaryOut(
        month=data.month,
        consolidated_by_currency=[
            CurrencyBalanceOut(
                currency=item.currency,
                posted_balance_cents=item.posted_balance_cents,
                projected_balance_cents=item.projected_balance_cents,
            )
            for item in data.consolidated_by_currency
        ],
        month_flow=[
            MonthFlowOut(
                currency=item.currency,
                month=item.month,
                income_cents=item.income_cents,
                expense_cents=item.expense_cents,
                net_cents=item.net_cents,
            )
            for item in data.month_flow
        ],
        accounts=[
            AccountBalanceOut(
                account_id=item.account_id,
                name=item.name,
                currency=item.currency,
                kind=item.kind,
                posted_balance_cents=item.posted_balance_cents,
                projected_balance_cents=item.projected_balance_cents,
            )
            for item in data.accounts
        ],
        upcoming=[
            UpcomingOut(
                id=item.id,
                account_id=item.account_id,
                operation_type=item.operation_type,
                status="pending",
                amount_cents=item.amount_cents,
                occurred_at=_iso(item.occurred_at),
                description=item.description,
            )
            for item in data.upcoming
        ],
        recent=[
            RecentOut(
                id=item.id,
                account_id=item.account_id,
                operation_type=item.operation_type,
                status=item.status,
                amount_cents=item.amount_cents,
                occurred_at=_iso(item.occurred_at),
                description=item.description,
            )
            for item in data.recent
        ],
    )


@router.get("/evolution", response_model=list[EvolutionOut])
async def evolution_route(
    user: CurrentUser,
    session: DbSession,
    months: int = Query(default=6, ge=1, le=24),
    until: str | None = Query(default=None),
) -> list[EvolutionOut]:
    await bind_current_user(session, user.id)
    try:
        normalized = parse_month(until)
        data = await dashboard_evolution(session, user.id, months, normalized)
    except DashboardError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return [
        EvolutionOut(
            currency=item.currency,
            month=item.month,
            income_cents=item.income_cents,
            expense_cents=item.expense_cents,
            end_balance_cents=item.end_balance_cents,
        )
        for item in data
    ]


@router.get("/month-comparison", response_model=ComparisonOut)
async def comparison_route(
    user: CurrentUser,
    session: DbSession,
    month: str | None = Query(default=None),
) -> ComparisonOut:
    await bind_current_user(session, user.id)
    try:
        normalized = parse_month(month)
        data = await dashboard_month_comparison(session, user.id, normalized)
    except DashboardError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ComparisonOut(
        current_month=data.current_month,
        previous_month=data.previous_month,
        rows=[
            ComparisonRowOut(
                currency=item.currency,
                current_income_cents=item.current_income_cents,
                current_expense_cents=item.current_expense_cents,
                current_net_cents=item.current_net_cents,
                previous_income_cents=item.previous_income_cents,
                previous_expense_cents=item.previous_expense_cents,
                previous_net_cents=item.previous_net_cents,
                delta_income_cents=item.delta_income_cents,
                delta_expense_cents=item.delta_expense_cents,
                delta_net_cents=item.delta_net_cents,
            )
            for item in data.rows
        ],
    )
