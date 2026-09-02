import uuid

import httpx
import pytest


def _csv(rows: list[str]) -> bytes:
    header = "occurred_at,amount_cents,kind,description,external_id\n"
    return (header + "\n".join(rows)).encode("utf-8")


async def _create_account(tx_client: httpx.AsyncClient) -> str:
    created = await tx_client.post(
        "/accounts",
        json={
            "name": f"Conta CSV {uuid.uuid4().hex[:6]}",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 0,
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


@pytest.mark.asyncio
async def test_csv_invalid_amount_returns_422_no_partial_import(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("bad.csv", _csv(["2026-09-01T10:00:00+00:00,abc,credit,pagamento,"]))},
        data={"source_name": "teste"},
    )
    assert response.status_code == 422, response.text
    detail = str(response.json()["detail"])
    assert "row 2" in detail

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert listing.json() == []


@pytest.mark.asyncio
async def test_csv_invalid_date_returns_422_no_partial_import(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("bad-date.csv", _csv(["31/02/2026,500,credit,pagamento,"]))},
        data={"source_name": "teste"},
    )
    assert response.status_code == 422, response.text
    detail = str(response.json()["detail"])
    assert "row 2" in detail

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert listing.json() == []


@pytest.mark.asyncio
async def test_csv_valid_rows_still_import(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={
            "file": (
                "ok.csv",
                _csv(
                    [
                        "2026-09-01T10:00:00+00:00,500,credit,pagamento,",
                        "2026-09-02T10:00:00+00:00,120,debit,compra,",
                    ]
                ),
            )
        },
        data={"source_name": "teste"},
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["imported_count"] == 2
    assert body["skipped_count"] == 0
