import uuid

import httpx
import pytest


async def _setup_user(tx_client: httpx.AsyncClient) -> dict[str, str]:
    brl = await tx_client.post(
        "/accounts",
        json={
            "name": "Corrente",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert brl.status_code == 201, brl.text
    usd = await tx_client.post(
        "/accounts",
        json={
            "name": "Poupança USD",
            "kind": "savings",
            "currency": "USD",
            "initial_balance_cents": 50000,
        },
    )
    assert usd.status_code == 201, usd.text
    return {"brl": brl.json()["id"], "usd": usd.json()["id"]}


async def _post_transaction(
    tx_client: httpx.AsyncClient,
    account_id: str,
    operation_type: str,
    amount_cents: int,
    occurred_at: str,
    status_expected: str = "posted",
) -> dict[str, object]:
    response = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": f"dash-{uuid.uuid4().hex[:12]}",
            "operation_type": operation_type,
            "amount_cents": amount_cents,
            "occurred_at": occurred_at,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == status_expected
    return dict(body)


@pytest.mark.asyncio
async def test_dashboard_summary_segregates_currencies_and_statuses(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_user(tx_client)

    await _post_transaction(tx_client, accounts["brl"], "deposit", 30000, "2026-07-10T12:00:00Z")
    await _post_transaction(tx_client, accounts["brl"], "withdrawal", 8000, "2026-07-15T12:00:00Z")
    await _post_transaction(tx_client, accounts["usd"], "deposit", 10000, "2026-07-12T12:00:00Z")
    await _post_transaction(
        tx_client,
        accounts["brl"],
        "withdrawal",
        20000,
        "2026-09-25T12:00:00Z",
        status_expected="pending",
    )

    summary = await tx_client.get("/dashboard/summary?month=2026-07")
    assert summary.status_code == 200, summary.text
    body = summary.json()

    currencies = {item["currency"]: item for item in body["consolidated_by_currency"]}
    assert set(currencies) == {"BRL", "USD"}
    assert currencies["BRL"]["posted_balance_cents"] == 122000
    assert currencies["BRL"]["projected_balance_cents"] == 102000
    assert currencies["USD"]["posted_balance_cents"] == 60000
    assert currencies["USD"]["projected_balance_cents"] == 60000

    flows = {item["currency"]: item for item in body["month_flow"]}
    assert flows["BRL"]["month"] == "2026-07"
    assert flows["BRL"]["income_cents"] == 30000
    assert flows["BRL"]["expense_cents"] == 8000
    assert flows["BRL"]["net_cents"] == 22000
    assert flows["USD"]["income_cents"] == 10000
    assert flows["USD"]["expense_cents"] == 0
    assert flows["USD"]["net_cents"] == 10000

    accounts_by_id = {item["account_id"]: item for item in body["accounts"]}
    assert accounts_by_id[accounts["brl"]]["posted_balance_cents"] == 122000
    assert accounts_by_id[accounts["brl"]]["projected_balance_cents"] == 102000
    assert accounts_by_id[accounts["usd"]]["posted_balance_cents"] == 60000

    upcoming = body["upcoming"]
    assert len(upcoming) == 1
    assert all(item["status"] == "pending" for item in upcoming)

    recent = body["recent"]
    assert len(recent) == 3
    assert all(item["status"] == "posted" for item in recent)
    occurred = [item["occurred_at"] for item in recent]
    assert occurred == sorted(occurred, reverse=True)


@pytest.mark.asyncio
async def test_dashboard_evolution_monthly_series_by_currency(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_user(tx_client)

    await _post_transaction(tx_client, accounts["brl"], "deposit", 50000, "2026-07-05T12:00:00Z")
    await _post_transaction(tx_client, accounts["brl"], "withdrawal", 10000, "2026-08-05T12:00:00Z")
    await _post_transaction(tx_client, accounts["brl"], "deposit", 7000, "2026-09-01T12:00:00Z")
    await _post_transaction(tx_client, accounts["usd"], "deposit", 9000, "2026-07-20T12:00:00Z")

    evolution = await tx_client.get("/dashboard/evolution?months=3&until=2026-09")
    assert evolution.status_code == 200, evolution.text
    body = evolution.json()

    brl = [item for item in body if item["currency"] == "BRL"]
    usd = [item for item in body if item["currency"] == "USD"]
    assert [item["month"] for item in brl] == ["2026-07", "2026-08", "2026-09"]
    assert brl[0]["income_cents"] == 50000
    assert brl[0]["expense_cents"] == 0
    assert brl[0]["end_balance_cents"] == 150000
    assert brl[1]["expense_cents"] == 10000
    assert brl[1]["end_balance_cents"] == 140000
    assert brl[2]["income_cents"] == 7000
    assert brl[2]["end_balance_cents"] == 147000

    assert [item["month"] for item in usd] == ["2026-07", "2026-08", "2026-09"]
    assert usd[0]["income_cents"] == 9000
    assert usd[0]["end_balance_cents"] == 59000
    assert usd[1]["income_cents"] == 0
    assert usd[1]["end_balance_cents"] == 59000
    assert usd[2]["end_balance_cents"] == 59000


@pytest.mark.asyncio
async def test_dashboard_month_comparison_current_vs_previous(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_user(tx_client)

    await _post_transaction(tx_client, accounts["brl"], "deposit", 40000, "2026-07-10T12:00:00Z")
    await _post_transaction(tx_client, accounts["brl"], "deposit", 65000, "2026-08-10T12:00:00Z")
    await _post_transaction(tx_client, accounts["brl"], "withdrawal", 5000, "2026-08-20T12:00:00Z")

    comparison = await tx_client.get("/dashboard/month-comparison?month=2026-08")
    assert comparison.status_code == 200, comparison.text
    body = comparison.json()
    assert body["current_month"] == "2026-08"
    assert body["previous_month"] == "2026-07"

    brl = next(item for item in body["rows"] if item["currency"] == "BRL")
    assert brl["current_income_cents"] == 65000
    assert brl["current_expense_cents"] == 5000
    assert brl["current_net_cents"] == 60000
    assert brl["previous_income_cents"] == 40000
    assert brl["previous_expense_cents"] == 0
    assert brl["previous_net_cents"] == 40000
    assert brl["delta_income_cents"] == 25000
    assert brl["delta_net_cents"] == 20000


@pytest.mark.asyncio
async def test_dashboard_is_isolated_per_user(
    tx_client: httpx.AsyncClient,
) -> None:
    accounts = await _setup_user(tx_client)
    await _post_transaction(tx_client, accounts["brl"], "deposit", 30000, "2026-07-10T12:00:00Z")

    email = f"dash-b-{uuid.uuid4().hex[:10]}@example.com"
    register = await tx_client.post(
        "/auth/register",
        json={"email": email, "name": "Dash B", "password": "Str0ng!Pass123"},
    )
    assert register.status_code in (200, 201)
    login = await tx_client.post(
        "/auth/login", data={"username": email, "password": "Str0ng!Pass123"}
    )
    token_b = str(login.json()["access_token"])

    foreign = await tx_client.get(
        "/dashboard/summary?month=2026-07",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert foreign.status_code == 200
    body = foreign.json()
    assert body["consolidated_by_currency"] == []
    assert body["accounts"] == []
    assert body["upcoming"] == []
    assert body["recent"] == []


@pytest.mark.asyncio
async def test_dashboard_rejects_invalid_month(tx_client: httpx.AsyncClient) -> None:
    bad = await tx_client.get("/dashboard/summary?month=09-2026")
    assert bad.status_code == 422
