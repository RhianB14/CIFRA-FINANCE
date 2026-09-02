import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reported_balance_cents: int
    note: str | None = Field(min_length=1, max_length=500, default=None)


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    reported_balance_cents: int
    ledger_balance_cents: int
    difference_cents: int
    status: str
    note: str | None
    created_at: datetime


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    source_name: str
    file_name: str
    file_sha256: str
    row_count: int
    imported_count: int
    skipped_count: int
    created_at: datetime
