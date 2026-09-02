from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class LedgerResult:
    transaction_id: UUID
    account_id: UUID
    kind: str
    amount_cents: int
    balance_after_cents: int
    balance_version: int
    created: bool
    reversal_of_id: UUID | None = None


class LedgerError(Exception):
    pass


class IdempotencyConflictError(LedgerError):
    pass


async def apply_ledger_movement(
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
    idempotency_key: str,
    operation_type: str,
    amount_cents: int,
    occurred_at: datetime,
    description: str | None = None,
    external_id: str | None = None,
    fingerprint: str | None = None,
    reverses_transaction_id: UUID | None = None,
) -> LedgerResult:
    raise NotImplementedError
