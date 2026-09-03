import asyncio
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import set_bypass_scope
from app.models import Account, RecurringTransaction, Transaction, User

LOCK_SQL = "SELECT pg_try_advisory_lock(841299640231)"


async def _seed_account(
    db_session: AsyncSession, name: str, pending_due: bool
) -> tuple[User, Account]:
    user = User(
        email=f"job-{uuid.uuid4().hex[:10]}@example.com",
        name=name,
        password_hash="x" * 20,
    )
    db_session.add(user)
    await db_session.commit()
    account = Account(
        user_id=user.id,
        name=f"{name} A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=100000,
        current_balance_cents=100000,
        current_balance_version=0,
    )
    db_session.add(account)
    await db_session.commit()
    if pending_due:
        db_session.add(
            Transaction(
                user_id=user.id,
                account_id=account.id,
                idempotency_key=f"job-{uuid.uuid4().hex[:12]}",
                payload_signature="a" * 64,
                kind="debit",
                operation_type="withdrawal",
                status="pending",
                amount_cents=10000,
                occurred_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await db_session.commit()
    return user, account


@pytest.mark.asyncio
async def test_daily_job_processes_all_accounts_and_users(
    db_session: AsyncSession,
) -> None:
    from app.jobs import run_daily_job

    await set_bypass_scope(db_session)
    _user_a, account_a = await _seed_account(db_session, "Job A", pending_due=True)
    _user_b, account_b = await _seed_account(db_session, "Job B", pending_due=True)

    recurring_user = User(
        email=f"job-rec-{uuid.uuid4().hex[:10]}@example.com",
        name="Job Rec",
        password_hash="x" * 20,
    )
    db_session.add(recurring_user)
    await db_session.commit()
    rec_account = Account(
        user_id=recurring_user.id,
        name="Job Rec A",
        kind="checking",
        currency="BRL",
        initial_balance_cents=50000,
        current_balance_cents=50000,
        current_balance_version=0,
    )
    db_session.add(rec_account)
    await db_session.commit()
    db_session.add(
        RecurringTransaction(
            user_id=recurring_user.id,
            account_id=rec_account.id,
            template_operation_type="deposit",
            template_amount_cents=1000,
            recurrence="monthly",
            starts_on=datetime.now(UTC).date().replace(day=1),
            next_run_on=datetime.now(UTC).date().replace(day=1),
            is_active=True,
        )
    )
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    result = await run_daily_job(factory)

    assert result.status == "completed"
    assert result.promoted == 2
    assert result.created >= 1
    assert result.errors == []
    assert result.exit_code == 0

    await db_session.refresh(account_a)
    await db_session.refresh(account_b)
    assert account_a.current_balance_cents == 90000
    assert account_b.current_balance_cents == 90000

    materialized = (
        (
            await db_session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.account_id == rec_account.id,
                    Transaction.fingerprint == f"recurring:{recurring_user.id}",
                )
            )
        )
        if False
        else (
            await db_session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.account_id == rec_account.id,
                    Transaction.idempotency_key.like("recurring:%"),
                )
            )
        )
    ).scalar_one()
    assert materialized >= 1


@pytest.mark.asyncio
async def test_daily_job_rerun_is_idempotent(db_session: AsyncSession) -> None:
    from app.jobs import run_daily_job

    await set_bypass_scope(db_session)
    _user, account = await _seed_account(db_session, "Rerun", pending_due=True)

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    first = await run_daily_job(factory)
    assert first.promoted == 1

    refreshed = await db_session.get(Account, account.id)
    assert refreshed is not None
    balance_after_first = refreshed.current_balance_cents

    second = await run_daily_job(factory)
    assert second.promoted == 0
    assert second.created == 0
    assert second.exit_code == 0

    refreshed_after = await db_session.get(Account, account.id)
    assert refreshed_after is not None
    assert refreshed_after.current_balance_cents == balance_after_first


@pytest.mark.asyncio
async def test_daily_job_concurrent_instances_do_not_double_post(
    migrated_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    from app.jobs import run_daily_job

    await set_bypass_scope(db_session)
    _user, account = await _seed_account(db_session, "Race", pending_due=True)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)

    first, second = await asyncio.gather(run_daily_job(factory), run_daily_job(factory))

    statuses = {first.status, second.status}
    assert "completed" in statuses
    assert "skipped_lock_held" in statuses

    await db_session.refresh(account)
    assert account.current_balance_cents == 90000
    assert account.current_balance_version == 1


@pytest.mark.asyncio
async def test_daily_job_per_unit_failure_is_isolated_and_sanitized(
    db_session: AsyncSession,
) -> None:
    from app.jobs import run_daily_job

    await set_bypass_scope(db_session)
    _user, _account = await _seed_account(db_session, "Iso", pending_due=True)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)

    import app.jobs.daily as daily_mod
    from app.services.scheduled import promote_due as _promote_due_original

    async def exploding(*args: object, **kwargs: object) -> int:
        raise RuntimeError("boom secret-value")

    daily_mod.promote_due = exploding
    try:
        result = await run_daily_job(factory)
    finally:
        daily_mod.promote_due = _promote_due_original

    assert result.exit_code == 1
    assert result.errors, "failure must be recorded"
    assert all("boom secret-value" not in str(err) for err in result.errors)
    assert all("secret" not in str(err).lower() for err in result.errors)


def _run_jobs_cli(args: list[str]) -> "subprocess.CompletedProcess[str]":
    import os
    import sys

    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, "-m", "app.jobs", *args],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.asyncio
async def test_daily_job_cli_documented_command(
    tx_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    import asyncio

    await set_bypass_scope(db_session)
    _user, account = await _seed_account(db_session, "CliRun", pending_due=True)

    completed = await asyncio.to_thread(_run_jobs_cli, ["--today", datetime.now(UTC).isoformat()])
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"status": "completed"' in completed.stdout
    assert '"promoted"' in completed.stdout

    await db_session.refresh(account)
    assert account.current_balance_cents == 90000

    lock_session = await cast(AsyncEngine, db_session.bind).connect()
    try:
        await lock_session.execute(text(LOCK_SQL))
        locked_run = await asyncio.to_thread(_run_jobs_cli, [])
        assert locked_run.returncode == 0, locked_run.stdout + locked_run.stderr
        assert '"status": "skipped_lock_held"' in locked_run.stdout
    finally:
        await lock_session.execute(text("SELECT pg_advisory_unlock(841299640231)"))
        await lock_session.close()
