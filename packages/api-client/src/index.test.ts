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
