import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest


async def _setup_accounts(tx_client: httpx.AsyncClient) -> dict[str, str]:
    brl = await tx_client.post(
        "/accounts",
        json={
            "name": "Principal",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert brl.status_code == 201, brl.text
    usd = await tx_client.post(
        "/accounts",
        json={
            "name": "Dolar",
            "kind": "savings",
            "currency": "USD",
        },
    )
    assert usd.status_code == 201, usd.text
    return {"brl": brl.json()["id"], "usd": usd.json()["id"]}


async def _post(
    tx_client: httpx.AsyncClient,
    account_id: str,
    operation_type: str,
    amount_cents: int,
    occurred_at: str,
) -> dict[str, object]:
    response = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": f"aud-{uuid.uuid4().hex[:12]}",
            "operation_type": operation_type,
            "amount_cents": amount_cents,
            "occurred_at": occurred_at,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.asyncio
async def test_archived_account_summary_no_key_error(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_accounts(tx_client)

    await _post(tx_client, accounts["brl"], "deposit", 30000, "2026-07-10T12:00:00Z")
    await _post(tx_client, accounts["brl"], "withdrawal", 5000, "2026-07-20T12:00:00Z")
    arch = await tx_client.patch(
        f"/accounts/{accounts['brl']}",
        json={"archived": True},
    )
    assert arch.status_code == 200, arch.text

    summary = await tx_client.get("/dashboard/summary?month=2026-07")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert {item["currency"] for item in body["accounts"]} == {"USD"}
    assert {item["currency"] for item in body["consolidated_by_currency"]} == {"USD"}
    assert {item["currency"] for item in body["month_flow"]} == {"USD"}


@pytest.mark.asyncio
async def test_archived_account_evolution_and_comparison_stable(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_accounts(tx_client)

    await _post(tx_client, accounts["brl"], "deposit", 40000, "2026-06-10T12:00:00Z")
    await _post(tx_client, accounts["brl"], "deposit", 20000, "2026-07-10T12:00:00Z")
    await _post(tx_client, accounts["usd"], "deposit", 12000, "2026-07-12T12:00:00Z")
    arch = await tx_client.patch(
        f"/accounts/{accounts['brl']}",
        json={"archived": True},
    )
    assert arch.status_code == 200, arch.text

    evolution = await tx_client.get("/dashboard/evolution?months=3&until=2026-07")
    assert evolution.status_code == 200, evolution.text
    assert {item["currency"] for item in evolution.json()} == {"USD"}

    comparison = await tx_client.get("/dashboard/month-comparison?month=2026-07")
    assert comparison.status_code == 200, comparison.text
    assert {row["currency"] for row in comparison.json()["rows"]} == {"USD"}


@pytest.mark.asyncio
async def test_archived_account_multiple_currencies_no_key_error(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_accounts(tx_client)

    await _post(tx_client, accounts["brl"], "deposit", 10000, "2026-07-01T12:00:00Z")
    await _post(tx_client, accounts["usd"], "deposit", 8000, "2026-07-02T12:00:00Z")
    arch_brl = await tx_client.patch(
        f"/accounts/{accounts['brl']}",
        json={"archived": True},
    )
    assert arch_brl.status_code == 200, arch_brl.text

    summary = await tx_client.get("/dashboard/summary?month=2026-07")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    currencies = {item["currency"] for item in body["consolidated_by_currency"]}
    assert currencies == {"USD"}
    flows = {item["currency"] for item in body["month_flow"]}
    assert flows == {"USD"}

    evolution = await tx_client.get("/dashboard/evolution?months=2&until=2026-07")
    assert evolution.status_code == 200, evolution.text
    evolution_currencies = {item["currency"] for item in evolution.json()}
    assert evolution_currencies == {"USD"}


@pytest.mark.asyncio
async def test_cross_currency_transfer_rejected_per_adr_0002(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_accounts(tx_client)

    transfer = await tx_client.post(
        f"/accounts/{accounts['brl']}/transactions/transfers",
        json={
            "idempotency_key": f"tf-{uuid.uuid4().hex[:12]}",
            "amount_cents": 25000,
            "target_account_id": accounts["usd"],
        },
    )
    assert transfer.status_code == 422, transfer.text
    assert "currency" in transfer.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_transfer_excluded_from_income_expense(
    tx_client: httpx.AsyncClient,
) -> None:
    second = await tx_client.post(
        "/accounts",
        json={"name": "Reserva", "kind": "savings", "currency": "BRL", "initial_balance_cents": 0},
    )
    assert second.status_code == 201, second.text
    main = await tx_client.post(
        "/accounts",
        json={
            "name": "Principal",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert main.status_code == 201, main.text
    main_id = main.json()["id"]
    second_id = second.json()["id"]

    transfer = await tx_client.post(
        f"/accounts/{main_id}/transactions/transfers",
        json={
            "idempotency_key": f"tf-{uuid.uuid4().hex[:12]}",
            "amount_cents": 25000,
            "target_account_id": second_id,
        },
    )
    assert transfer.status_code == 201, transfer.text
    legs = transfer.json()
    assert {leg["operation_type"] for leg in legs} == {"transfer_out", "transfer_in"}

    month = "2026-08"
    summary = await tx_client.get(f"/dashboard/summary?month={month}")
    assert summary.status_code == 200, summary.text
    body = summary.json()

    brl_flow = next(f for f in body["month_flow"] if f["currency"] == "BRL")
    assert brl_flow["income_cents"] == 0, "transfer_out must not inflate income"
    assert brl_flow["expense_cents"] == 0, "transfer_out must not inflate expense"

    balances = {item["account_id"]: item for item in body["accounts"]}
    assert balances[main_id]["posted_balance_cents"] == 75000
    assert balances[second_id]["posted_balance_cents"] == 25000

    evolution = await tx_client.get(f"/dashboard/evolution?months=1&until={month}")
    assert evolution.status_code == 200, evolution.text
    points = {item["currency"]: item for item in evolution.json()}
    assert points["BRL"]["end_balance_cents"] == 100000
    assert points["BRL"]["income_cents"] == 0
    assert points["BRL"]["expense_cents"] == 0


@pytest.mark.asyncio
async def test_internal_transfer_same_currency_excluded_too(
    tx_client: httpx.AsyncClient,
) -> None:
    second = await tx_client.post(
        "/accounts",
        json={"name": "Reserva", "kind": "savings", "currency": "BRL", "initial_balance_cents": 0},
    )
    assert second.status_code == 201, second.text
    main = await tx_client.post(
        "/accounts",
        json={
            "name": "Principal",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert main.status_code == 201, main.text
    main_id = main.json()["id"]
    second_id = second.json()["id"]

    transfer = await tx_client.post(
        f"/accounts/{main_id}/transactions/transfers",
        json={
            "idempotency_key": f"tf-{uuid.uuid4().hex[:12]}",
            "amount_cents": 30000,
            "target_account_id": second_id,
        },
    )
    assert transfer.status_code == 201, transfer.text
    legs = transfer.json()
    assert {leg["operation_type"] for leg in legs} == {"transfer_out", "transfer_in"}

    month = "2026-08"
    summary = await tx_client.get(f"/dashboard/summary?month={month}")
    assert summary.status_code == 200, summary.text
    body = summary.json()

    brl_flow = next(f for f in body["month_flow"] if f["currency"] == "BRL")
    assert brl_flow["income_cents"] == 0, "transfer must not inflate income"
    assert brl_flow["expense_cents"] == 0, "transfer must not inflate expense"

    balances = {item["account_id"]: item for item in body["accounts"]}
    assert balances[main_id]["posted_balance_cents"] == 70000
    assert balances[second_id]["posted_balance_cents"] == 30000


@pytest.mark.asyncio
async def test_archived_account_excluded_from_upcoming_and_recent(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_accounts(tx_client)
    active_id = accounts["usd"]
    archived_id = accounts["brl"]

    await _post(tx_client, archived_id, "deposit", 40000, "2026-07-01T12:00:00Z")
    scheduled = await tx_client.post(
        f"/accounts/{archived_id}/transactions",
        json={
            "idempotency_key": f"aud-{uuid.uuid4().hex[:12]}",
            "operation_type": "withdrawal",
            "amount_cents": 5000,
            "occurred_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )
    assert scheduled.status_code == 201, scheduled.text
    arch = await tx_client.patch(
        f"/accounts/{archived_id}",
        json={"archived": True},
    )
    assert arch.status_code == 200, arch.text

    await _post(tx_client, active_id, "deposit", 25000, "2026-07-05T12:00:00Z")
    await _post(tx_client, active_id, "withdrawal", 3000, "2026-07-06T12:00:00Z")
    active_pending = await tx_client.post(
        f"/accounts/{active_id}/transactions",
        json={
            "idempotency_key": f"aud-{uuid.uuid4().hex[:12]}",
            "operation_type": "deposit",
            "amount_cents": 15000,
            "occurred_at": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        },
    )
    assert active_pending.status_code == 201, active_pending.text

    summary = await tx_client.get("/dashboard/summary?month=2026-07")
    assert summary.status_code == 200, summary.text
    body = summary.json()

    balances = {item["account_id"]: item for item in body["accounts"]}
    assert set(balances) == {active_id}, "archived account must not appear"
    assert balances[active_id]["posted_balance_cents"] == 22000
    assert balances[active_id]["projected_balance_cents"] == 37000

    upcoming_ids = {item["id"] for item in body["upcoming"]}
    assert upcoming_ids == {active_pending.json()["id"]}, (
        "upcoming must show only active-account pendings"
    )

    recent = {item["id"]: item for item in body["recent"]}
    assert all(item["account_id"] == active_id for item in body["recent"])
    recent_accounts = {item["account_id"] for item in body["recent"]}
    assert recent_accounts == {active_id}, "recent must show only active-account posts"
    assert recent, "active account has posted transactions and must appear in recent"
