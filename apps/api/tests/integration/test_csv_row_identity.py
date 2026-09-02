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
            "name": f"Conta Ident {uuid.uuid4().hex[:6]}",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 0,
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


@pytest.mark.asyncio
async def test_csv_reordered_rows_do_not_duplicate(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    first_rows = [
        "2026-09-01T10:00:00+00:00,500,credit,pagamento aluguel,",
        "2026-09-02T10:00:00+00:00,120,debit,compra mercado,",
    ]
    first = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("a.csv", _csv(first_rows))},
        data={"source_name": "banco-x"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["imported_count"] == 2

    reordered_rows = list(reversed(first_rows))
    second = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={"file": ("b.csv", _csv(reordered_rows))},
        data={"source_name": "banco-x"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["imported_count"] == 0
    assert second.json()["skipped_count"] == 2

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert len(listing.json()) == 2


@pytest.mark.asyncio
async def test_csv_duplicate_rows_within_file_are_skipped(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={
            "file": (
                "dup.csv",
                _csv(
                    [
                        "2026-09-01T10:00:00+00:00,500,credit,pagamento aluguel,",
                        "2026-09-01T10:00:00+00:00,500,credit,pagamento aluguel,",
                    ]
                ),
            )
        },
        data={"source_name": "banco-x"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported_count"] == 1
    assert response.json()["skipped_count"] == 1

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_same_file_in_different_account_creates_new_batch(
    tx_client: httpx.AsyncClient,
) -> None:
    account_a = await _create_account(tx_client)
    account_b = await _create_account(tx_client)
    rows = [
        "2026-09-01T10:00:00+00:00,500,credit,pagamento aluguel,",
        "2026-09-02T10:00:00+00:00,120,debit,compra mercado,",
    ]
    first = await tx_client.post(
        f"/accounts/{account_a}/imports",
        files={"file": ("f.csv", _csv(rows))},
        data={"source_name": "banco-x"},
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["imported_count"] == 2

    second = await tx_client.post(
        f"/accounts/{account_b}/imports",
        files={"file": ("f.csv", _csv(rows))},
        data={"source_name": "banco-x"},
    )
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["id"] != first_body["id"]
    assert second_body["imported_count"] == 2
    assert second_body["skipped_count"] == 0


@pytest.mark.asyncio
async def test_csv_external_id_up_to_255_is_accepted(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    max_id = "x" * 255
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={
            "file": (
                "max.csv",
                _csv([f"2026-09-01T10:00:00+00:00,500,credit,pagamento,{max_id}"]),
            )
        },
        data={"source_name": "banco-x"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported_count"] == 1

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_csv_external_id_over_255_is_domain_error(
    tx_client: httpx.AsyncClient,
) -> None:
    account_id = await _create_account(tx_client)
    long_id = "x" * 256
    response = await tx_client.post(
        f"/accounts/{account_id}/imports",
        files={
            "file": (
                "long.csv",
                _csv([f"2026-09-01T10:00:00+00:00,500,credit,pagamento,{long_id}"]),
            )
        },
        data={"source_name": "banco-x"},
    )
    assert response.status_code == 422, response.text

    listing = await tx_client.get(f"/accounts/{account_id}/transactions")
    assert listing.status_code == 200
    assert listing.json() == []
