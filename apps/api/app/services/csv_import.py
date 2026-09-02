import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImportBatch, Transaction
from app.services.ledger import apply_ledger_movement


class ImportError_(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ImportResult:
    batch_id: UUID
    row_count: int
    imported_count: int
    skipped_count: int
    file_sha256: str


def _row_fingerprint(
    occurred_at_raw: str,
    amount_raw: str,
    kind_raw: str,
    description: str | None,
    external_id: str | None,
) -> str:
    payload = "|".join(
        [occurred_at_raw, amount_raw, kind_raw, description or "", external_id or ""]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def import_csv(
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
    source_name: str,
    file_name: str,
    content: bytes,
) -> ImportResult:
    sha = hashlib.sha256(content).hexdigest()
    existing_batch = await session.execute(
        select(ImportBatch).where(
            ImportBatch.user_id == user_id,
            ImportBatch.account_id == account_id,
            ImportBatch.file_sha256 == sha,
        )
    )
    previous = existing_batch.scalar_one_or_none()
    if previous is not None:
        return ImportResult(
            batch_id=previous.id,
            row_count=previous.row_count,
            imported_count=0,
            skipped_count=previous.imported_count,
            file_sha256=previous.file_sha256,
        )
    text_content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_content))
    if reader.fieldnames is None:
        raise ImportError_("csv file has no header")
    required = {"occurred_at", "amount_cents", "kind"}
    missing = required - set(reader.fieldnames)
    if missing:
        raise ImportError_("missing columns: " + ",".join(sorted(missing)))

    row_count = 0
    imported = 0
    skipped = 0
    for index, row in enumerate(reader):
        row_count += 1
        external_id = (row.get("external_id") or "").strip() or None
        description = (row.get("description") or "").strip() or None
        occurred_at_raw = (row.get("occurred_at") or "").strip()
        amount_raw = (row.get("amount_cents") or "").strip()
        kind_raw = (row.get("kind") or "").strip().lower()
        if not occurred_at_raw or not amount_raw or kind_raw not in {"credit", "debit"}:
            raise ImportError_(f"row {index + 2}: invalid row")
        try:
            amount_cents = int(amount_raw)
        except ValueError:
            raise ImportError_(f"row {index + 2}: invalid amount") from None
        if amount_cents <= 0:
            raise ImportError_(f"row {index + 2}: amount must be positive")
        try:
            occurred_at = datetime.fromisoformat(occurred_at_raw.replace("Z", "+00:00"))
        except ValueError:
            raise ImportError_(f"row {index + 2}: invalid occurred_at") from None
        if external_id is not None and len(external_id) > 255:
            raise ImportError_(f"row {index + 2}: external_id too long")
        fingerprint = _row_fingerprint(
            occurred_at_raw, amount_raw, kind_raw, description, external_id
        )
        key = f"import:{fingerprint}"
        operation = "deposit" if kind_raw == "credit" else "withdrawal"
        op_key = f"{key}:dep" if kind_raw == "credit" else f"{key}:wd"
        existing = await session.execute(
            select(Transaction.id).where(
                Transaction.account_id == account_id,
                Transaction.idempotency_key == op_key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue
        await apply_ledger_movement(
            session,
            account_id=account_id,
            user_id=user_id,
            idempotency_key=op_key,
            operation_type=operation,
            amount_cents=amount_cents,
            occurred_at=occurred_at,
            description=description,
            external_id=external_id,
            fingerprint=fingerprint,
        )
        imported += 1

    batch_values = dict(
        id=uuid.uuid4(),
        user_id=user_id,
        account_id=account_id,
        source_name=source_name,
        file_name=file_name,
        file_sha256=sha,
        row_count=row_count,
        imported_count=imported,
        skipped_count=skipped,
    )
    batch_stmt = (
        pg_insert(ImportBatch)
        .values(**batch_values)
        .on_conflict_do_nothing(
            index_elements=[
                ImportBatch.user_id,
                ImportBatch.account_id,
                ImportBatch.file_sha256,
            ]
        )
        .returning(ImportBatch.id)
    )
    batch_row = (await session.execute(batch_stmt)).first()
    if batch_row is None:
        winner = await session.execute(
            select(ImportBatch).where(
                ImportBatch.user_id == user_id,
                ImportBatch.account_id == account_id,
                ImportBatch.file_sha256 == sha,
            )
        )
        winner_batch = winner.scalar_one_or_none()
        if winner_batch is None:
            raise ImportError_("import batch vanished during concurrent import")
        return ImportResult(
            batch_id=winner_batch.id,
            row_count=winner_batch.row_count,
            imported_count=0,
            skipped_count=winner_batch.imported_count,
            file_sha256=winner_batch.file_sha256,
        )
    await session.commit()
    return ImportResult(
        batch_id=batch_row.id,
        row_count=row_count,
        imported_count=imported,
        skipped_count=skipped,
        file_sha256=sha,
    )
