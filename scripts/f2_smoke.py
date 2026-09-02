import asyncio
import os
import uuid

import httpx


async def main() -> None:
    base = os.environ.get("SMOKE_BASE_URL", "http://localhost:18000")
    suffix = uuid.uuid4().hex[:8]
    email = f"f2-smoke-{suffix}@example.com"
    password = "correct horse battery staple"
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        register = await http.post(
            "/auth/register",
            json={"email": email, "name": "F2 Smoke", "password": password},
        )
        assert register.status_code in (200, 201), register.text
        login = await http.post("/auth/login", data={"username": email, "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        account_a = await http.post(
            "/accounts",
            json={"name": "Conta A", "kind": "checking", "currency": "BRL", "initial_balance_cents": 100000},
            headers=headers,
        )
        assert account_a.status_code == 201, account_a.text
        account_b = await http.post(
            "/accounts",
            json={"name": "Conta B", "kind": "checking", "currency": "BRL", "initial_balance_cents": 0},
            headers=headers,
        )
        assert account_b.status_code == 201, account_b.text
        a_id = account_a.json()["id"]
        b_id = account_b.json()["id"]

        deposit = await http.post(
            f"/accounts/{a_id}/transactions",
            json={"idempotency_key": f"smoke-dep-{suffix}", "operation_type": "deposit", "amount_cents": 50000, "description": "dep"},
            headers=headers,
        )
        assert deposit.status_code == 201, deposit.text
        transfer = await http.post(
            f"/accounts/{a_id}/transactions/transfers",
            json={"idempotency_key": f"smoke-tr-{suffix}", "amount_cents": 32000, "target_account_id": b_id},
            headers=headers,
        )
        assert transfer.status_code == 201, transfer.text

        balance_a = await http.get(f"/accounts/{a_id}/balance", headers=headers)
        balance_b = await http.get(f"/accounts/{b_id}/balance", headers=headers)
        assert balance_a.json()["current_balance_cents"] == 118000, balance_a.text
        assert balance_b.json()["current_balance_cents"] == 20000, balance_b.text
        print("F2-SMOKE-OK: A=1180 B=200 (cents 118000/20000)")


if __name__ == "__main__":
    asyncio.run(main())
