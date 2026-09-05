import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx


async def main() -> None:
    base = os.environ.get("SMOKE_BASE_URL", "http://localhost:18000")
    oracle_path = Path(
        os.environ.get(
            "F4_ORACLE_PATH", str(Path(__file__).parents[1] / "docs" / "f4-accounting-oracle.json")
        )
    )
    oracle = json.loads(oracle_path.read_text())
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        email = f"f4-smoke-{suffix}@example.com"
        password = "correct horse battery staple"
        register = await http.post(
            "/auth/register", json={"email": email, "name": "F4 Smoke", "password": password}
        )
        assert register.status_code in (200, 201), register.text
        login = await http.post("/auth/login", data={"username": email, "password": password})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        account = await http.post(
            "/accounts",
            headers=headers,
            json={
                "name": "Conta F4",
                "kind": "checking",
                "currency": "BRL",
                "initial_balance_cents": oracle["before_payment"]["payer_balance_cents"],
            },
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]
        card = await http.post(
            "/cards",
            headers=headers,
            json={"name": "Cartao F4", "currency": "BRL", **oracle["card"], "last_four": "4242"},
        )
        assert card.status_code == 201, card.text
        card_id = card.json()["id"]
        created = []
        for purchase in oracle["purchases"]:
            response = await http.post(
                f"/cards/{card_id}/purchases",
                headers=headers,
                json={
                    "idempotency_key": f"{purchase['key']}-{suffix}",
                    "amount_cents": purchase["amount_cents"],
                    "purchase_date": purchase["date"],
                    "installments": purchase["installments"],
                    "description": "F4 oracle",
                },
            )
            assert response.status_code == 201, response.text
            created.extend(response.json())
        assert len(created) == 5
        assert sum(item["amount_cents"] for item in created) == sum(
            purchase["amount_cents"] for purchase in oracle["purchases"]
        )
        exposure = await http.get(f"/cards/{card_id}/exposure", headers=headers)
        assert exposure.status_code == 200, exposure.text
        assert exposure.json()["exposure_cents"] == oracle["before_payment"]["card_exposure_cents"]
        assert exposure.json()["available_cents"] == oracle["before_payment"]["available_cents"]
        balance = await http.get(f"/accounts/{account_id}/balance", headers=headers)
        assert (
            balance.json()["current_balance_cents"]
            == oracle["before_payment"]["payer_balance_cents"]
        )
        invoices = await http.get(f"/cards/{card_id}/invoices", headers=headers)
        assert invoices.status_code == 200, invoices.text
        periods = {f"{item['year']}-{item['month']:02d}": item for item in invoices.json()}
        for period, expected in oracle["before_payment"]["invoices"].items():
            assert periods[period]["total_cents"] == expected["total_cents"]
        replay = await http.post(
            f"/cards/{card_id}/purchases",
            headers=headers,
            json={
                "idempotency_key": f"{oracle['purchases'][2]['key']}-{suffix}",
                "amount_cents": 10001,
                "purchase_date": "2024-02-29",
                "installments": 3,
                "description": "F4 oracle",
            },
        )
        assert replay.status_code == 201, replay.text
        assert [item["id"] for item in replay.json()] == [item["id"] for item in created[-3:]]
        reversal = await http.post(
            f"/cards/purchases/{created[-1]['id']}/reversal",
            headers=headers,
            json={"idempotency_key": f"f4-reversal-{suffix}"},
        )
        assert reversal.status_code == 201, reversal.text
        assert (
            len(reversal.json())
            == oracle["after_installment_reversal"]["installment_reversal_rows"]
        )
        exposure_after = await http.get(f"/cards/{card_id}/exposure", headers=headers)
        assert exposure_after.status_code == 200, exposure_after.text
        after = exposure_after.json()["exposure_cents"]
        expected = oracle["after_installment_reversal"]["card_exposure_cents"]
        assert after == expected, f"exposure after reversal {after} != {expected}"
        print(
            f"F4-SMOKE-OK exposure={after} available={exposure_after.json()['available_cents']} invoices={len(periods)} reversals={len(reversal.json())}"
        )


if __name__ == "__main__":
    asyncio.run(main())
