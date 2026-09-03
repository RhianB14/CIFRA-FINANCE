import uuid

import httpx
import pytest


async def _create_recurring(tx_client: httpx.AsyncClient) -> dict[str, object]:
    account = await tx_client.post(
        "/accounts",
        json={
            "name": f"Rec-{uuid.uuid4().hex[:6]}",
            "kind": "checking",
            "currency": "BRL",
            "initial_balance_cents": 0,
        },
    )
    assert account.status_code == 201, account.text
    created = await tx_client.post(
        "/recurring-transactions",
        json={
            "account_id": account.json()["id"],
            "template_operation_type": "deposit",
            "template_amount_cents": 1000,
            "recurrence": "monthly",
            "starts_on": "2026-09-05",
            "ends_on": "2026-12-05",
            "template_description": "aluguel",
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


@pytest.mark.asyncio
async def test_patch_omitted_field_preserves_current_value(
    tx_client: httpx.AsyncClient,
) -> None:
    recurring = await _create_recurring(tx_client)
    recurring_id = str(recurring["id"])

    patched = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"is_active": False},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["is_active"] is False
    assert body["template_description"] == "aluguel"
    assert body["ends_on"] == "2026-12-05"


@pytest.mark.asyncio
async def test_patch_informed_field_replaces_value(
    tx_client: httpx.AsyncClient,
) -> None:
    recurring = await _create_recurring(tx_client)
    recurring_id = str(recurring["id"])

    patched = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"template_description": "condominio"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["template_description"] == "condominio"
    assert body["ends_on"] == "2026-12-05", "ends_on omitted must be preserved"


@pytest.mark.asyncio
async def test_patch_explicit_null_clears_optional_fields(
    tx_client: httpx.AsyncClient,
) -> None:
    recurring = await _create_recurring(tx_client)
    recurring_id = str(recurring["id"])

    patched = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"template_description": None, "ends_on": None},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["template_description"] is None, "explicit null must clear the description"
    assert body["ends_on"] is None, "explicit null must clear ends_on"


@pytest.mark.asyncio
async def test_patch_null_then_inform_restores(
    tx_client: httpx.AsyncClient,
) -> None:
    recurring = await _create_recurring(tx_client)
    recurring_id = str(recurring["id"])

    cleared = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"template_description": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["template_description"] is None

    restored = await tx_client.patch(
        f"/recurring-transactions/{recurring_id}",
        json={"template_description": "novo valor"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["template_description"] == "novo valor"
