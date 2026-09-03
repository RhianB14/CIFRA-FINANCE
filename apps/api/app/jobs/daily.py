import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Account, CreditCard, User
from app.services.cards import close_card_invoices
from app.services.recurring import materialize_recurring as materialize_recurring
from app.services.scheduled import promote_due as promote_due

logger = logging.getLogger("cifra.jobs.daily")

ADVISORY_LOCK_KEY = 841299640231


@dataclass(frozen=True, slots=True)
class DailyJobResult:
    status: str
    promoted: int
    created: int
    replayed: int
    paused: int
    invoices_closed: int
    accounts_scanned: int
    users_scanned: int
    errors: list[str] = field(default_factory=list)
    exit_code: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "promoted": self.promoted,
                "created": self.created,
                "replayed": self.replayed,
                "paused": self.paused,
                "invoices_closed": self.invoices_closed,
                "accounts_scanned": self.accounts_scanned,
                "users_scanned": self.users_scanned,
                "error_count": len(self.errors),
                "errors": self.errors,
                "exit_code": self.exit_code,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            },
            sort_keys=True,
        )


def _sanitize_error(unit: str, unit_id: UUID, exc: Exception) -> str:
    return f"{unit}:{unit_id}:{type(exc).__name__}"


async def _set_bypass(session: AsyncSession) -> None:
    from app.core.db import set_bypass_scope

    await set_bypass_scope(session)


async def run_daily_job(
    session_factory: async_sessionmaker[AsyncSession],
    today: datetime | None = None,
) -> DailyJobResult:
    started_at = datetime.now(UTC)
    errors: list[str] = []
    promoted_total = 0
    created_total = 0
    replayed_total = 0
    paused_total = 0
    invoices_closed_total = 0
    accounts_scanned = 0
    users_scanned = 0
    status = "completed"
    exit_code = 0

    now = today if today is not None else datetime.now(UTC)
    engine: AsyncEngine = session_factory.kw["bind"]

    async with engine.connect() as lock_connection:
        lock_result = await lock_connection.execute(
            select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY))
        )
        lock_acquired = bool(lock_result.scalar_one())
        if not lock_acquired:
            return DailyJobResult(
                status="skipped_lock_held",
                promoted=0,
                created=0,
                replayed=0,
                paused=0,
                invoices_closed=0,
                accounts_scanned=0,
                users_scanned=0,
                errors=[],
                exit_code=0,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        try:
            async with session_factory() as scope:
                await _set_bypass(scope)
                account_rows = await scope.execute(
                    select(Account.id, Account.user_id).order_by(Account.created_at, Account.id)
                )
                account_units = [(row.id, row.user_id) for row in account_rows.all()]

            for account_id, owner_id in account_units:
                accounts_scanned += 1
                try:
                    async with session_factory() as session:
                        await _set_bypass(session)
                        promoted = await promote_due(
                            session,
                            account_id=account_id,
                            user_id=owner_id,
                            today=now,
                        )
                        await session.commit()
                        promoted_total += promoted
                except Exception as exc:
                    errors.append(_sanitize_error("account", account_id, exc))

            async with session_factory() as scope:
                await _set_bypass(scope)
                user_rows = await scope.execute(
                    select(User.id)
                    .where(User.id.in_(select(Account.user_id).distinct()))
                    .order_by(User.created_at, User.id)
                )
                user_ids = [row[0] for row in user_rows.all()]

            async with session_factory() as scope:
                await _set_bypass(scope)
                card_rows = await scope.execute(
                    select(CreditCard.id)
                    .where(CreditCard.archived_at.is_(None))
                    .order_by(CreditCard.created_at, CreditCard.id)
                )
                card_ids = [row[0] for row in card_rows.all()]

            for card_id in card_ids:
                try:
                    async with session_factory() as session:
                        await _set_bypass(session)
                        card = await session.get(CreditCard, card_id)
                        if card is None:
                            continue
                        closed = await close_card_invoices(session, card, now.date())
                        await session.commit()
                        invoices_closed_total += closed
                except Exception as exc:
                    errors.append(_sanitize_error("card", card_id, exc))

            for user_id in user_ids:
                users_scanned += 1
                try:
                    async with session_factory() as session:
                        await _set_bypass(session)
                        outcome = await materialize_recurring(
                            session, user_id=user_id, today=now.date()
                        )
                        await session.commit()
                        created_total += outcome.created
                        replayed_total += outcome.replayed
                        paused_total += outcome.paused
                except Exception as exc:
                    errors.append(_sanitize_error("user", user_id, exc))
        finally:
            try:
                await lock_connection.execute(select(func.pg_advisory_unlock(ADVISORY_LOCK_KEY)))
                await lock_connection.commit()
            except Exception:
                logger.exception("failed to release daily job advisory lock")

    if errors:
        status = "completed_with_errors"
        exit_code = 1
    return DailyJobResult(
        status=status,
        promoted=promoted_total,
        created=created_total,
        replayed=replayed_total,
        paused=paused_total,
        invoices_closed=invoices_closed_total,
        accounts_scanned=accounts_scanned,
        users_scanned=users_scanned,
        errors=errors,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
