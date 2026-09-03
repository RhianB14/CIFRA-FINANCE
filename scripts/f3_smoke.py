import asyncio
import os
import uuid
from datetime import datetime, timedelta

import httpx


async def main() -> None:
    base = os.environ.get("SMOKE_BASE_URL", "http://localhost:18000")
    suffix = uuid.uuid4().hex[:8]
    email = f"f3-smoke-{suffix}@example.com"
    password = "correct horse battery staple"
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        register = await http.post(
            "/auth/register",
            json={"email": email, "name": "F3 Smoke", "password": password},
        )
        assert register.status_code in (200, 201), register.text
        login = await http.post("/auth/login", data={"username": email, "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        account = await http.post(
            "/accounts",
            json={"name": "Conta F3", "kind": "checking", "currency": "BRL", "initial_balance_cents": 100000},
            headers=headers,
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]

        deposit = await http.post(
            f"/accounts/{account_id}/transactions",
            json={
                "idempotency_key": f"f3-dep-{suffix}",
                "operation_type": "deposit",
                "amount_cents": 30000,
                "description": "posted",
                "occurred_at": "2026-08-05T12:00:00Z",
            },
            headers=headers,
        )
        assert deposit.status_code == 201, deposit.text
        assert deposit.json()["status"] == "posted", deposit.text

        now = datetime.now() + timedelta(days=10)
        future_iso = now.strftime("%Y-%m-%dT12:00:00Z")
        scheduled = await http.post(
            f"/accounts/{account_id}/transactions",
            json={
                "idempotency_key": f"f3-sched-{suffix}",
                "operation_type": "withdrawal",
                "amount_cents": 5000,
                "description": "scheduled",
                "occurred_at": future_iso,
            },
            headers=headers,
        )
        assert scheduled.status_code == 201, scheduled.text
        assert scheduled.json()["status"] == "pending", scheduled.text

        balance = await http.get(f"/accounts/{account_id}/balance", headers=headers)
        assert balance.json()["current_balance_cents"] == 130000, balance.text
        projected = await http.get(
            f"/accounts/{account_id}/balance?projected=true", headers=headers
        )
        assert projected.json()["projected_balance_cents"] == 125000, projected.text

        recurring = await http.post(
            "/recurring-transactions",
            json={
                "account_id": account_id,
                "template_operation_type": "deposit",
                "template_amount_cents": 1000,
                "recurrence": "monthly",
                "starts_on": "2026-06-05",
                "ends_on": "2026-08-31",
            },
            headers=headers,
        )
        assert recurring.status_code == 201, recurring.text
        recurring_id = recurring.json()["id"]

        summary = await http.get("/dashboard/summary?month=2026-08", headers=headers)
        assert summary.status_code == 200, summary.text
        body = summary.json()
        currencies = {item["currency"]: item for item in body["consolidated_by_currency"]}
        assert "BRL" in currencies, summary.text
        brl = currencies["BRL"]
        assert brl["posted_balance_cents"] == 130000, summary.text
        assert brl["projected_balance_cents"] == 125000, summary.text
        assert len(body["upcoming"]) == 1, summary.text
        upcoming_ids = {item["id"] for item in body["upcoming"]}
        assert scheduled.json()["id"] in upcoming_ids, summary.text

        evolution = await http.get(
            "/dashboard/evolution?months=3&until=2026-08", headers=headers
        )
        assert evolution.status_code == 200, evolution.text

        comparison = await http.get("/dashboard/month-comparison?month=2026-08", headers=headers)
        assert comparison.status_code == 200, comparison.text

        print(
            "F3-SMOKE-OK: posted=1300 projected=1250 upcoming=1 "
            f"recurring={recurring_id} currencies=BRL-only"
        )


if __name__ == "__main__":
    asyncio.run(main())
