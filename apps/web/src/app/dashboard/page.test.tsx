import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Line: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}));

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const summaryDefaults = {
  month: "2026-08",
  consolidated_by_currency: [],
  month_flow: [],
  accounts: [],
  upcoming: [],
  recent: [],
};

const fullSummary = {
  month: "2026-08",
  consolidated_by_currency: [
    { currency: "BRL", posted_balance_cents: 122000, projected_balance_cents: 102000 },
    { currency: "USD", posted_balance_cents: 60000, projected_balance_cents: 60000 },
  ],
  month_flow: [
    {
      currency: "BRL",
      month: "2026-08",
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
      description: "Aluguel",
    },
  ],
  recent: [
    {
      id: "t-1",
      account_id: "a-1",
      operation_type: "deposit",
      status: "posted",
      amount_cents: 30000,
      occurred_at: "2026-08-10T12:00:00+00:00",
      description: null,
    },
  ],
};

const evolution = [
  {
    currency: "BRL",
    month: "2026-07",
    income_cents: 0,
    expense_cents: 0,
    end_balance_cents: 100000,
  },
  {
    currency: "BRL",
    month: "2026-08",
    income_cents: 30000,
    expense_cents: 8000,
    end_balance_cents: 122000,
  },
];

const comparison = {
  current_month: "2026-08",
  previous_month: "2026-07",
  rows: [
    {
      currency: "BRL",
      current_income_cents: 30000,
      current_expense_cents: 8000,
      current_net_cents: 22000,
      previous_income_cents: 0,
      previous_expense_cents: 0,
      previous_net_cents: 0,
      delta_income_cents: 30000,
      delta_expense_cents: 8000,
      delta_net_cents: 22000,
    },
  ],
};

function mockClient(overrides: {
  summary?: Promise<unknown>;
  evolution?: Promise<unknown>;
  comparison?: Promise<unknown>;
}) {
  return {
    dashboardSummary: vi.fn(() => overrides.summary ?? Promise.resolve(summaryDefaults)),
    dashboardEvolution: vi.fn(() => overrides.evolution ?? Promise.resolve([])),
    dashboardMonthComparison: vi.fn(
      () =>
        overrides.comparison ??
        Promise.resolve({ current_month: "", previous_month: "", rows: [] }),
    ),
  };
}

async function renderDashboard(client: ReturnType<typeof mockClient>) {
  vi.doMock("@cifra/api-client", () => ({
    createApiClient: () => client,
  }));
  const { default: DashboardPage } = await import("./page");
  const view = render(await DashboardPage({ searchParams: Promise.resolve({ token: "tok-1" }) }));
  return view;
}

describe("Dashboard page", () => {
  afterEach(() => {
    vi.doUnmock("@cifra/api-client");
    vi.resetModules();
  });

  it("renders consolidated balances per currency without mixing totals", async () => {
    await renderDashboard(
      mockClient({ summary: Promise.resolve(fullSummary), evolution: Promise.resolve(evolution) }),
    );

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeTruthy();
    const brlBlock = screen.getByTestId("currency-BRL");
    expect(brlBlock.textContent).toContain("1.220,00");
    expect(brlBlock.textContent).toContain("BRL");
    const usdBlock = screen.getByTestId("currency-USD");
    expect(usdBlock.textContent).toContain("600,00");
    expect(usdBlock.textContent).not.toContain("1.220,00");
  });

  it("renders month flow, upcoming and recent sections", async () => {
    await renderDashboard(
      mockClient({ summary: Promise.resolve(fullSummary), evolution: Promise.resolve(evolution) }),
    );

    expect(screen.getByText(/Entradas:/)).toBeTruthy();
    expect(screen.getByText(/Saídas:/)).toBeTruthy();
    expect(screen.getByText(/Fluxo do mês:/)).toBeTruthy();
    expect(screen.getByText("Aluguel")).toBeTruthy();
    expect(screen.getByText("Próximos agendados")).toBeTruthy();
    expect(screen.getByText("Últimos lançamentos")).toBeTruthy();
  });

  it("renders empty state when the user has no data", async () => {
    await renderDashboard(mockClient({}));

    expect(screen.getByText("Nenhuma conta cadastrada.")).toBeTruthy();
    expect(screen.getByText("Nenhum lançamento agendado.")).toBeTruthy();
    expect(screen.getByText("Nenhum lançamento registrado.")).toBeTruthy();
  });

  it("renders error state when the API fails", async () => {
    const boom = Promise.reject(new Error("boom"));
    boom.catch(() => {});
    await renderDashboard(mockClient({ summary: boom }));

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Não foi possível carregar o dashboard.")).toBeTruthy();
  });

  it("renders evolution and comparison charts per currency", async () => {
    await renderDashboard(
      mockClient({
        summary: Promise.resolve(fullSummary),
        evolution: Promise.resolve(evolution),
        comparison: Promise.resolve(comparison),
      }),
    );

    expect(screen.getByTestId("evolution-BRL")).toBeTruthy();
    expect(screen.getByTestId("comparison-BRL")).toBeTruthy();
  });
});
