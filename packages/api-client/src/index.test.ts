import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "./index";

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status,
  });

describe("createApiClient", () => {
  it("requests the live endpoint and returns its response", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ status: "alive", service: "cifra-api" }));
    const client = createApiClient({ baseUrl: "http://api.test", request });

    await expect(client.live()).resolves.toEqual({ status: "alive", service: "cifra-api" });
    expect(request).toHaveBeenCalledWith("http://api.test/health/live", { cache: "no-store" });
  });

  it("requests the ready endpoint after removing a trailing slash", async () => {
    const ready = {
      status: "ready" as const,
      dependencies: { postgres: "healthy", redis: "healthy", storage: "healthy" } as const,
    };
    const request = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(ready));
    const client = createApiClient({ baseUrl: "http://api.test/", request });

    await expect(client.ready()).resolves.toEqual(ready);
    expect(request).toHaveBeenCalledWith("http://api.test/health/ready", { cache: "no-store" });
  });

  it("throws an explicit error for a non-OK response", async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 503));
    const client = createApiClient({ baseUrl: "http://api.test", request });

    await expect(client.ready()).rejects.toThrow("Cifra API request failed with status 503");
  });
});

describe("dashboard methods", () => {
  const token = "tok-123";

  const sampleSummary = {
    month: "2026-08",
    consolidated_by_currency: [
      {
        currency: "BRL",
        posted_balance_cents: 122000,
        projected_balance_cents: 102000,
      },
    ],
    month_flow: [
      {
        currency: "BRL",
        month: "2026-07",
        income_cents: 30000,
        expense_cents: 8000,
        net_cents: 22000,
      },
    ],
    accounts: [
      {
        account_id: "a-1",
        name: "Corrente",
        currency: "BRL",
        kind: "checking",
        posted_balance_cents: 122000,
        projected_balance_cents: 102000,
      },
    ],
    upcoming: [
      {
        id: "t-9",
        account_id: "a-1",
        operation_type: "withdrawal",
        status: "pending",
        amount_cents: 20000,
        occurred_at: "2026-09-25T12:00:00+00:00",
        description: null,
      },
    ],
    recent: [
      {
        id: "t-1",
        account_id: "a-1",
        operation_type: "deposit",
        status: "posted",
        amount_cents: 30000,
        occurred_at: "2026-07-10T12:00:00+00:00",
        description: null,
      },
    ],
  };

  it("requests the dashboard summary for a month with auth header", async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(sampleSummary));
    const client = createApiClient({ baseUrl: "http://api.test", request });

    await expect(client.dashboardSummary(token, "2026-08")).resolves.toEqual(sampleSummary);
    expect(request).toHaveBeenCalledWith("http://api.test/dashboard/summary?month=2026-08", {
      method: "GET",
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
  });

  it("omits the month parameter when not provided", async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(sampleSummary));
    const client = createApiClient({ baseUrl: "http://api.test", request });

    await expect(client.dashboardSummary(token)).resolves.toEqual(sampleSummary);
    expect(request).toHaveBeenCalledWith("http://api.test/dashboard/summary", {
      method: "GET",
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
  });

  it("requests evolution and month comparison endpoints", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          current_month: "2026-08",
          previous_month: "2026-07",
          rows: [],
        }),
      );
    const client = createApiClient({ baseUrl: "http://api.test", request });

    await expect(client.dashboardEvolution(token, 6, "2026-09")).resolves.toEqual([]);
    expect(request).toHaveBeenCalledWith(
      "http://api.test/dashboard/evolution?months=6&until=2026-09",
      {
        method: "GET",
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` },
      },
    );

    await expect(client.dashboardMonthComparison(token, "2026-08")).resolves.toEqual({
      current_month: "2026-08",
      previous_month: "2026-07",
      rows: [],
    });
    expect(request).toHaveBeenCalledWith(
      "http://api.test/dashboard/month-comparison?month=2026-08",
      {
        method: "GET",
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
  });
});
