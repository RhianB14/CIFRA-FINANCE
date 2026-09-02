import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AccountsPage from "./page";

const listAccounts = vi.fn();

vi.mock("@cifra/api-client", () => ({
  createApiClient: () => ({
    listAccounts: (...args: unknown[]) => listAccounts(...args),
  }),
}));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`redirect:${url}`);
  },
}));

describe("AccountsPage", () => {
  it("lists accounts with formatted balances", async () => {
    listAccounts.mockResolvedValue([
      {
        id: "11111111-1111-1111-1111-111111111111",
        name: "Conta A",
        kind: "checking",
        currency: "BRL",
        current_balance_cents: 118000,
        balance_version: 3,
        archived: false,
      },
      {
        id: "22222222-2222-2222-2222-222222222222",
        name: "Conta B",
        kind: "checking",
        currency: "BRL",
        current_balance_cents: 20000,
        balance_version: 2,
        archived: false,
      },
    ]);
    const params = Promise.resolve({ token: "t0ken" });
    const page = await AccountsPage({ searchParams: params });
    render(page);
    expect(screen.getByText("Conta A")).toBeDefined();
    expect(screen.getByText("R$ 1.180,00")).toBeDefined();
    expect(screen.getByText("Conta B")).toBeDefined();
    expect(screen.getByText("R$ 200,00")).toBeDefined();
  });

  it("redirects to home without token", async () => {
    const params = Promise.resolve({});
    await expect(AccountsPage({ searchParams: params })).rejects.toThrow("redirect:/");
  });
});
