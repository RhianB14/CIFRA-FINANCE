import asyncio
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asyncpg.exceptions import UniqueViolationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, CardInvoice, CreditCard, InvoicePayment, Transaction, User
from app.services.cards import (
    CardError,
    apply_invoice_payment,
    card_exposure,
    create_card,
    create_card_purchase,
    reverse_card_purchase,
    reverse_invoice_payment,
)
from app.services.ledger import IdempotencyConflictError

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
AUDIT_DATABASE = "cifra_f4_audit_20260904"
CHECK_CONSTRAINTS = (
    "transactions_card_linkage",
    "transactions_card_operation",
    "transactions_installment_pair",
    "transactions_installment_range",
)
REVERSAL_UNIQUE_INDEX = "uq_invoice_payments_reversed_payment"


async def _setup(session: AsyncSession) -> tuple[User, Account, CreditCard]:
    user = User(email=f"{uuid4().hex}@example.com", name="T", password_hash="x")
    session.add(user)
    await session.flush()
    payer = Account(
        user_id=user.id,
        name="Conta",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    session.add(payer)
    await session.flush()
    card = await create_card(session, user.id, "Cartao", "BRL", 100000, 25, 10, "4321")
    return user, payer, card


async def _purchase(
    session: AsyncSession,
    user: User,
    card: CreditCard,
    key: str,
    amount: int = 10000,
) -> list[Transaction]:
    return await create_card_purchase(
        session, card.id, user.id, key, amount, date(2026, 4, 24), 1, "Compra"
    )


async def _invoice(session: AsyncSession, card: CreditCard) -> CardInvoice:
    rows = await session.execute(
        sa.select(CardInvoice).where(
            CardInvoice.card_id == card.id, CardInvoice.year == 2026, CardInvoice.month == 4
        )
    )
    invoice = rows.scalar_one()
    assert invoice.id is not None
    return invoice


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _snapshot(scope: AsyncSession, account_id: UUID) -> tuple[int, int]:
    row = await scope.execute(
        sa.select(Account.current_balance_cents, Account.current_balance_version).where(
            Account.id == account_id
        )
    )
    found = row.one()
    return int(found[0]), int(found[1])


async def _payment_worker(
    engine: AsyncEngine,
    state: tuple[UUID, UUID, UUID],
    key: str,
    amount: int,
    barrier: asyncio.Barrier,
) -> str:
    user_id, payer_id, invoice_id = state
    factory = _factory(engine)
    async with factory() as scope:
        await set_bypass_scope(scope)
        await barrier.wait()
        try:
            await apply_invoice_payment(scope, invoice_id, user_id, payer_id, key, amount, T0)
            await scope.commit()
        except CardError:
            await scope.rollback()
            return "rejected"
        except IdempotencyConflictError:
            await scope.rollback()
            return "conflict"
        except sa.exc.IntegrityError as exc:
            await scope.rollback()
            cause = str(exc.__cause__ or exc)
            if isinstance(exc.__cause__, UniqueViolationError) or "duplicate key" in cause:
                return f"integrity:{cause.splitlines()[0]}"
            raise
        return "ok"


async def _reversal_worker(
    engine: AsyncEngine,
    payment_id: UUID,
    user_id: UUID,
    key: str,
    barrier: asyncio.Barrier,
) -> str:
    factory = _factory(engine)
    async with factory() as scope:
        await set_bypass_scope(scope)
        await barrier.wait()
        try:
            await reverse_invoice_payment(scope, payment_id, user_id, key)
            await scope.commit()
        except CardError:
            await scope.rollback()
            return "rejected"
        except IdempotencyConflictError:
            await scope.rollback()
            return "conflict"
        except sa.exc.IntegrityError as exc:
            await scope.rollback()
            cause = str(exc.__cause__ or exc)
            if isinstance(exc.__cause__, UniqueViolationError) or "duplicate key" in cause:
                return f"integrity:{cause.splitlines()[0]}"
            raise
        return "ok"


async def test_concurrent_payments_cannot_exceed_invoice_total(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    state = (user.id, payer.id, invoice.id)

    barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        _payment_worker(migrated_engine, state, "race-1", 6000, barrier),
        _payment_worker(migrated_engine, state, "race-2", 6000, barrier),
    )

    assert sorted(results) == ["ok", "rejected"], results
    factory = _factory(migrated_engine)
    async with factory() as check:
        await set_bypass_scope(check)
        paid = await check.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(InvoicePayment.amount_cents), 0)).where(
                InvoicePayment.kind == "payment",
                InvoicePayment.invoice_id == state[2],
            )
        )
        assert paid == 6000
        balance, version = await _snapshot(check, state[1])
        assert (balance, version) == (100000 - 6000, 1)
        pairs = await check.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.invoice_id == state[2],
                Transaction.operation_type == "card_payment",
                Transaction.charge_kind == "payment",
            )
        )
        assert pairs == 2


async def test_concurrent_valid_payments_settle_without_lost_update(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    state = (user.id, payer.id, invoice.id)

    barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        _payment_worker(migrated_engine, state, "valid-1", 4000, barrier),
        _payment_worker(migrated_engine, state, "valid-2", 4000, barrier),
    )

    assert list(results) == ["ok", "ok"], results
    factory = _factory(migrated_engine)
    async with factory() as check:
        await set_bypass_scope(check)
        paid = await check.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(InvoicePayment.amount_cents), 0)).where(
                InvoicePayment.kind == "payment",
                InvoicePayment.invoice_id == state[2],
            )
        )
        assert paid == 8000
        balance, version = await _snapshot(check, payer.id)
        assert (balance, version) == (100000 - 8000, 2)
        debit_rows = (
            (
                await check.execute(
                    sa.select(Transaction).where(
                        Transaction.account_id == state[1],
                        Transaction.operation_type == "card_payment",
                        Transaction.charge_kind == "payment",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(debit_rows) == 2
        by_key = {row.idempotency_key: row for row in debit_rows}
        assert sorted(
            (
                by_key["valid-1"].result_balance_after_cents,
                by_key["valid-2"].result_balance_after_cents,
            )
        ) == [92000, 96000]
        assert by_key["valid-1"].result_balance_version != by_key["valid-2"].result_balance_version


async def test_reverse_purchase_and_concurrent_purchase_preserve_exposure_identity(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    purchase = await _purchase(db_session, user, card, "a1", 3000)
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    anchor_id = purchase[0].id
    user_id = user.id
    card_id = card.id
    companion_id = card.account_id

    factory = _factory(migrated_engine)
    barrier = asyncio.Barrier(2)

    async def reverse_worker() -> str:
        async with factory() as scope:
            await set_bypass_scope(scope)
            await barrier.wait()
            try:
                await reverse_card_purchase(scope, anchor_id, user_id, "ra")
                await scope.commit()
            except CardError as exc:
                await scope.rollback()
                return f"rejected:{exc}"
            return "ok"

    async def purchase_worker() -> str:
        async with factory() as scope:
            await set_bypass_scope(scope)
            await barrier.wait()
            try:
                await create_card_purchase(
                    scope, card_id, user_id, "b1", 7000, date(2026, 4, 24), 1, "Compra B"
                )
                await scope.commit()
            except CardError:
                await scope.rollback()
                return "rejected"
            return "ok"

    reverse_result, purchase_result = await asyncio.gather(reverse_worker(), purchase_worker())
    assert reverse_result == "ok", reverse_result
    assert purchase_result == "ok", purchase_result

    async with factory() as check:
        await set_bypass_scope(check)
        purchase_count = await check.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.invoice_id == invoice.id,
                Transaction.operation_type == "card_purchase",
            )
        )
        assert purchase_count == 2
        reversal_count = await check.scalar(
            sa.select(sa.func.count(Transaction.id)).where(Transaction.reversal_of_id == anchor_id)
        )
        assert reversal_count == 1
        companion_balance, companion_version = await _snapshot(check, companion_id)
        assert (companion_balance, companion_version) == (-7000, 3)
        fresh_card = await check.get(CreditCard, card_id)
        assert fresh_card is not None
        exposure = await card_exposure(check, fresh_card)
        assert exposure["exposure_cents"] == 7000
        assert exposure["exposure_cents"] == -companion_balance


async def test_duplicate_idempotency_key_concurrent_payments_have_single_effect(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1")
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    state = (user.id, payer.id, invoice.id)

    barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        _payment_worker(migrated_engine, state, "dup", 4000, barrier),
        _payment_worker(migrated_engine, state, "dup", 4000, barrier),
    )

    assert all(result in ("ok", "rejected", "conflict") for result in results), results
    factory = _factory(migrated_engine)
    async with factory() as check:
        await set_bypass_scope(check)
        payment_count = await check.scalar(
            sa.select(sa.func.count(InvoicePayment.id)).where(InvoicePayment.invoice_id == state[2])
        )
        assert payment_count == 1
        paid = await check.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(InvoicePayment.amount_cents), 0)).where(
                InvoicePayment.invoice_id == state[2]
            )
        )
        assert paid == 4000
        balance, version = await _snapshot(check, payer.id)
        assert (balance, version) == (100000 - 4000, 1)


async def test_second_reversal_with_different_key_is_rejected_without_mutation(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1", 4000)
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    factory = _factory(migrated_engine)
    async with factory() as scope:
        await set_bypass_scope(scope)
        payment = await apply_invoice_payment(
            scope, invoice.id, user.id, payer.id, "pay-1", 4000, T0
        )
        await scope.commit()
        payment_id = payment.id

    first = await _reversal_worker(migrated_engine, payment_id, user.id, "r1", asyncio.Barrier(1))
    assert first == "ok", first
    async with factory() as replay_scope:
        await set_bypass_scope(replay_scope)
        existing = await replay_scope.scalar(
            sa.select(InvoicePayment).where(
                InvoicePayment.kind == "reversal",
                InvoicePayment.reversed_by_id == payment_id,
            )
        )
        assert existing is not None
        before = await _snapshot(replay_scope, payer.id)
        replayed = await reverse_invoice_payment(replay_scope, payment_id, user.id, "r1")
        await replay_scope.commit()
        after = await _snapshot(replay_scope, payer.id)
        assert replayed.id == existing.id
        assert after == before
    second = await _reversal_worker(migrated_engine, payment_id, user.id, "r2", asyncio.Barrier(1))
    assert second == "rejected", second

    async with factory() as check:
        await set_bypass_scope(check)
        reversal_count = await check.scalar(
            sa.select(sa.func.count(InvoicePayment.id)).where(
                InvoicePayment.kind == "reversal", InvoicePayment.reversed_by_id == payment_id
            )
        )
        assert reversal_count == 1
        reversal_txns = await check.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.user_id == user.id,
                Transaction.charge_kind == "payment_reversal",
            )
        )
        assert reversal_txns == 2
        balance, version = await _snapshot(check, payer.id)
        assert (balance, version) == (100000 - 4000 + 4000, 2)


async def test_concurrent_reversals_of_same_payment_have_single_effect(
    db_session: AsyncSession, migrated_engine: AsyncEngine
) -> None:
    user, payer, card = await _setup(db_session)
    await _purchase(db_session, user, card, "p1", 4000)
    invoice = await _invoice(db_session, card)
    await db_session.commit()
    factory = _factory(migrated_engine)
    async with factory() as scope:
        await set_bypass_scope(scope)
        payment = await apply_invoice_payment(
            scope, invoice.id, user.id, payer.id, "pay-1", 4000, T0
        )
        await scope.commit()
        payment_id = payment.id

    barrier = asyncio.Barrier(2)
    results = await asyncio.gather(
        _reversal_worker(migrated_engine, payment_id, user.id, "cr1", barrier),
        _reversal_worker(migrated_engine, payment_id, user.id, "cr2", barrier),
    )

    assert sorted(results) == ["ok", "rejected"], results
    assert not any(str(result).startswith("integrity:") for result in results), results
    async with factory() as check:
        await set_bypass_scope(check)
        reversal_count = await check.scalar(
            sa.select(sa.func.count(InvoicePayment.id)).where(
                InvoicePayment.kind == "reversal", InvoicePayment.reversed_by_id == payment_id
            )
        )
        assert reversal_count == 1
        reversal_txns = await check.scalar(
            sa.select(sa.func.count(Transaction.id)).where(
                Transaction.user_id == user.id,
                Transaction.charge_kind == "payment_reversal",
            )
        )
        assert reversal_txns == 2
        balance, version = await _snapshot(check, payer.id)
        assert (balance, version) == (100000 - 4000 + 4000, 2)


def _audit_alembic_config() -> Config:
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2]
    configuration = Config(str(api_root / "alembic.ini"))
    configuration.set_main_option("script_location", str(api_root / "migrations"))
    configuration.set_main_option(
        "sqlalchemy.url",
        _audit_dsn(AUDIT_DATABASE).replace("postgresql://", "postgresql+asyncpg://"),
    )
    return configuration


def _audit_dsn(database: str) -> str:
    from tests.conftest import admin_dsn

    return admin_dsn(database)


async def _audit_admin(
    query: str, database: str = "postgres"
) -> list[tuple[bool | str | None, ...]]:
    import asyncpg

    connection = await asyncpg.connect(_audit_dsn(database))
    try:
        rows = await connection.fetch(query)
        return [tuple(row) for row in rows]
    finally:
        await connection.close()


async def test_migration_cycle_creates_validated_checks_and_reversal_uniqueness() -> None:

    await _audit_admin(f'DROP DATABASE IF EXISTS "{AUDIT_DATABASE}" WITH (FORCE)')
    await _audit_admin(f'CREATE DATABASE "{AUDIT_DATABASE}"')
    config = _audit_alembic_config()
    try:
        await asyncio.to_thread(command.upgrade, config, "0012")
        await asyncio.to_thread(command.upgrade, config, "0013")

        checks: dict[str, bool] = {}
        for name in CHECK_CONSTRAINTS:
            rows = await _audit_admin(
                "SELECT conname, convalidated FROM pg_constraint "
                f"WHERE conrelid = 'transactions'::regclass AND conname = '{name}'",
                database=AUDIT_DATABASE,
            )
            assert len(rows) == 1, (name, rows)
            checks[str(rows[0][0])] = bool(rows[0][1])
        assert set(checks) == set(CHECK_CONSTRAINTS)
        assert all(checks.values()), checks

        index_rows = await _audit_admin(
            "SELECT indexdef FROM pg_indexes "
            f"WHERE tablename = 'invoice_payments' AND indexname = '{REVERSAL_UNIQUE_INDEX}'",
            database=AUDIT_DATABASE,
        )
        assert len(index_rows) == 1, index_rows
        assert "CREATE UNIQUE" in str(index_rows[0][0])
        assert "reversed_by_id" in str(index_rows[0][0])

        await asyncio.to_thread(command.downgrade, config, "0012")
        gone = await _audit_admin(
            "SELECT indexname FROM pg_indexes "
            f"WHERE tablename = 'invoice_payments' AND indexname = '{REVERSAL_UNIQUE_INDEX}'",
            database=AUDIT_DATABASE,
        )
        assert gone == []
        await asyncio.to_thread(command.upgrade, config, "0013")
        back = await _audit_admin(
            "SELECT indexname FROM pg_indexes "
            f"WHERE tablename = 'invoice_payments' AND indexname = '{REVERSAL_UNIQUE_INDEX}'",
            database=AUDIT_DATABASE,
        )
        assert len(back) == 1
    finally:
        await _audit_admin(f'DROP DATABASE IF EXISTS "{AUDIT_DATABASE}" WITH (FORCE)')
