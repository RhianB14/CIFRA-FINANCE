import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Account


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    kind: str
    currency: str = Field(min_length=3, max_length=3)
    initial_balance_cents: int = Field(ge=0, default=0)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(min_length=1, max_length=255, default=None)
    kind: str | None = None
    archived: bool | None = None
    expected_version: int | None = Field(ge=0, default=None)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    currency: str
    initial_balance_cents: int
    current_balance_cents: int
    current_balance_version: int
    archived_at: datetime | None
    created_at: datetime


def account_to_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        name=account.name,
        kind=account.kind,
        currency=account.currency,
        initial_balance_cents=account.initial_balance_cents,
        current_balance_cents=account.current_balance_cents,
        current_balance_version=account.current_balance_version,
        archived_at=account.archived_at,
        created_at=account.created_at,
    )
