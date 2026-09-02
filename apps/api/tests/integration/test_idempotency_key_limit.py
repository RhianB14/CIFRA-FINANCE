import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.schemas.transactions import TransferCreate


@pytest.mark.asyncio
async def test_idempotency_key_boundary_128_ok_129_rejected(
    tx_client: httpx.AsyncClient,
) -> None:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": "Conta Key Limit",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 0,
        },
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    key_128 = "k" * 128
    ok = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": key_128,
            "operation_type": "deposit",
            "amount_cents": 100,
            "occurred_at": "2026-09-01T10:00:00Z",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["balance_after_cents"] == 100

    key_129 = "x" * 129
    rejected = await tx_client.post(
        f"/accounts/{account_id}/transactions",
        json={
            "idempotency_key": key_129,
            "operation_type": "deposit",
            "amount_cents": 100,
            "occurred_at": "2026-09-01T10:00:00Z",
        },
    )
    assert rejected.status_code == 422, rejected.text

    transfer_129 = await tx_client.post(
        f"/accounts/{account_id}/transactions/transfers",
        json={
            "idempotency_key": key_129,
            "amount_cents": 50,
            "target_account_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-01T10:00:00Z",
        },
    )
    assert transfer_129.status_code == 422, transfer_129.text


def test_transfer_in_leg_key_fits_128_limit() -> None:
    key = "k" * 128
    payload = TransferCreate(
        idempotency_key=key,
        amount_cents=50,
        target_account_id=uuid.uuid4(),
        occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    assert len(payload.idempotency_key) <= 128
    assert payload.idempotency_key == key
