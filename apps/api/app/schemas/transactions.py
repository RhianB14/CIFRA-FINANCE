import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    operation_type: str
    amount_cents: int = Field(gt=0)
    occurred_at: datetime
    description: str | None = Field(min_length=1, max_length=500, default=None)
    external_id: str | None = Field(min_length=1, max_length=255, default=None)
    fingerprint: str | None = Field(min_length=1, max_length=255, default=None)


class ReversalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    expected_version: int | None = Field(ge=0, default=None)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    operation_type: str
    status: str
    amount_cents: int
    occurred_at: datetime
    description: str | None
    external_id: str | None
    fingerprint: str | None
    reversal_of_id: uuid.UUID | None
    category_id: uuid.UUID | None
    balance_after_cents: int = 0
    balance_version: int = 0
    created_at: datetime


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    amount_cents: int = Field(gt=0)
    target_account_id: uuid.UUID
    occurred_at: datetime | None = None
