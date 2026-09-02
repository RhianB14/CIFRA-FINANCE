import httpx
import pytest


@pytest.mark.asyncio
async def test_transaction_crud_moves_balance_and_reverses(tx_client: httpx.AsyncClient) -> None:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Conta Tx HTTP",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    deposit = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": "http-dep-1",
            "operation_type": "deposit",
            "amount_cents": 50000,
            "occurred_at": "2026-09-02T12:00:00Z",
            "description": "depósito inicial",
        },
    )
    assert deposit.status_code == 201, deposit.text
    assert deposit.json()["balance_after_cents"] == 150000

    replay = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": "http-dep-1",
            "operation_type": "deposit",
            "amount_cents": 50000,
            "occurred_at": "2026-09-02T12:00:00Z",
            "description": "depósito inicial",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == deposit.json()["id"]

    conflict = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": "http-dep-1",
            "operation_type": "deposit",
            "amount_cents": 12345,
            "occurred_at": "2026-09-02T12:00:00Z",
        },
    )
    assert conflict.status_code == 409

    listed = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    withdrawal = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": "http-wd-1",
            "operation_type": "withdrawal",
            "amount_cents": 32000,
            "occurred_at": "2026-09-02T13:00:00Z",
        },
    )
    assert withdrawal.status_code == 201
    withdrawal_id = withdrawal.json()["id"]

    reversal = await tx_client.post(
        f"/accounts/{account_id}/transactions/{withdrawal_id}/reversal",
        json={"idempotency_key": "http-rev-1"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["balance_after_cents"] == 150000

    account = await tx_client.get(f"/accounts/{account_id}")
    assert account.json()["current_balance_cents"] == 150000
    assert account.json()["current_balance_version"] == 3

    projected = await tx_client.get(f"/accounts/{account_id}/balance?projected=true")
    assert projected.status_code == 200
    assert projected.json()["projected_balance_cents"] == 150000


@pytest.mark.asyncio
async def test_transaction_unknown_fields_rejected(tx_client: httpx.AsyncClient) -> None:
    created = await tx_client.post(
        "/accounts",
        json={"name": "V", "kind": "checking", "currency": "BRL"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]
    bad = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": "k",
            "operation_type": "deposit",
            "amount_cents": 100,
            "occurred_at": "2026-09-02T12:00:00Z",
            "nonsense_field": True,
        },
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_transfer_route_moves_both_balances(tx_client: httpx.AsyncClient) -> None:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Origem",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 100000,
        },
    )
    origin = created.json()["id"]
    other = await tx_client.post(
        "/accounts",
        json={"name": "Destino", "kind": "checking", "currency": "BRL", "initial_balance_cents": 0},
    )
    target = other.json()["id"]
    response = await tx_client.post(
        f"/accounts/{origin}/transactions/transfers",
        json={"idempotency_key": "tr-1", "amount_cents": 32000, "target_account_id": target},
    )
    assert response.status_code == 201, response.text
    a = await tx_client.get(f"/accounts/{origin}/balance")
    b = await tx_client.get(f"/accounts/{target}/balance")
    assert a.json()["current_balance_cents"] == 68000
    assert b.json()["current_balance_cents"] == 32000
