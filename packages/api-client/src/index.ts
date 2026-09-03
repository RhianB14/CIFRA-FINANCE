import type { LiveStatus, ReadyStatus } from "@cifra/shared-types";

export type ApiClientOptions = {
  baseUrl: string;
  request?: typeof fetch;
  token?: string;
};

export type AccountInput = {
  name: string;
  kind: string;
  currency: string;
  initial_balance_cents: number;
};

export type AccountPatchInput = {
  name?: string;
  archived?: boolean;
  expected_version?: number;
};

export type Account = {
  id: string;
  name: string;
  kind: string;
  currency: string;
  current_balance_cents: number;
  balance_version: number;
  archived: boolean;
};

export type TransactionInput = {
  idempotency_key: string;
  operation_type: string;
  amount_cents: number;
  occurred_at: string;
  description?: string;
};

export type AccountBalance = {
  account_id: string;
  current_balance_cents: number;
  projected_balance_cents: number;
};

export type CurrencyBalance = {
  currency: string;
  posted_balance_cents: number;
  projected_balance_cents: number;
};

export type DashboardAccountBalance = {
  account_id: string;
  name: string;
  currency: string;
  kind: string;
  posted_balance_cents: number;
  projected_balance_cents: number;
};

export type MonthFlow = {
  currency: string;
  month: string;
  income_cents: number;
  expense_cents: number;
  net_cents: number;
};

export type UpcomingItem = {
  id: string;
  account_id: string;
  operation_type: string;
  status: string;
  amount_cents: number;
  occurred_at: string;
  description: string | null;
};

export type RecentItem = {
  id: string;
  account_id: string;
  operation_type: string;
  status: string;
  amount_cents: number;
  occurred_at: string;
  description: string | null;
};

export type DashboardSummary = {
  month: string;
  consolidated_by_currency: CurrencyBalance[];
  month_flow: MonthFlow[];
  accounts: DashboardAccountBalance[];
  upcoming: UpcomingItem[];
  recent: RecentItem[];
};

export type EvolutionPoint = {
  currency: string;
  month: string;
  income_cents: number;
  expense_cents: number;
  end_balance_cents: number;
};

export type MonthComparisonRow = {
  currency: string;
  current_income_cents: number;
  current_expense_cents: number;
  current_net_cents: number;
  previous_income_cents: number;
  previous_expense_cents: number;
  previous_net_cents: number;
  delta_income_cents: number;
  delta_expense_cents: number;
  delta_net_cents: number;
};

export type MonthComparison = {
  current_month: string;
  previous_month: string;
  rows: MonthComparisonRow[];
};

export type CifraApiClient = {
  live: () => Promise<LiveStatus>;
  ready: () => Promise<ReadyStatus>;
  listAccounts: (token: string) => Promise<Account[]>;
  createAccount: (token: string, input: AccountInput) => Promise<Account>;
  updateAccount: (token: string, id: string, patch: AccountPatchInput) => Promise<Account>;
  deleteAccount: (token: string, id: string) => Promise<void>;
  createTransaction: (
    token: string,
    accountId: string,
    input: TransactionInput,
  ) => Promise<AccountBalance>;
  dashboardSummary: (token: string, month?: string) => Promise<DashboardSummary>;
  dashboardEvolution: (token: string, months: number, until?: string) => Promise<EvolutionPoint[]>;
  dashboardMonthComparison: (token: string, month?: string) => Promise<MonthComparison>;
};

const requestJson = async <T>(request: typeof fetch, url: string): Promise<T> => {
  const response = await request(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Cifra API request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
};

const authedJson = async <T>(
  request: typeof fetch,
  url: string,
  token: string,
  method: string,
  body?: unknown,
): Promise<T> => {
  const response = await request(url, {
    method,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Cifra API request failed with status ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
};

export const createApiClient = ({ baseUrl, request = fetch }: ApiClientOptions): CifraApiClient => {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");
  return {
    live: () => requestJson<LiveStatus>(request, `${normalizedBaseUrl}/health/live`),
    ready: () => requestJson<ReadyStatus>(request, `${normalizedBaseUrl}/health/ready`),
    listAccounts: (token) =>
      authedJson<Account[]>(request, `${normalizedBaseUrl}/accounts`, token, "GET"),
    createAccount: (token, input) =>
      authedJson<Account>(request, `${normalizedBaseUrl}/accounts`, token, "POST", input),
    updateAccount: (token, id, patch) =>
      authedJson<Account>(request, `${normalizedBaseUrl}/accounts/${id}`, token, "PATCH", patch),
    deleteAccount: async (token, id) => {
      await authedJson<undefined>(request, `${normalizedBaseUrl}/accounts/${id}`, token, "DELETE");
    },
    createTransaction: (token, accountId, input) =>
      authedJson<AccountBalance>(
        request,
        `${normalizedBaseUrl}/accounts/${accountId}/transactions`,
        token,
        "POST",
        input,
      ),
    dashboardSummary: (token, month) =>
      authedJson<DashboardSummary>(
        request,
        month === undefined
          ? `${normalizedBaseUrl}/dashboard/summary`
          : `${normalizedBaseUrl}/dashboard/summary?month=${encodeURIComponent(month)}`,
        token,
        "GET",
      ),
    dashboardEvolution: (token, months, until) => {
      const params = new URLSearchParams({ months: String(months) });
      if (until !== undefined) {
        params.set("until", until);
      }
      return authedJson<EvolutionPoint[]>(
        request,
        `${normalizedBaseUrl}/dashboard/evolution?${params.toString()}`,
        token,
        "GET",
      );
    },
    dashboardMonthComparison: (token, month) =>
      authedJson<MonthComparison>(
        request,
        month === undefined
          ? `${normalizedBaseUrl}/dashboard/month-comparison`
          : `${normalizedBaseUrl}/dashboard/month-comparison?month=${encodeURIComponent(month)}`,
        token,
        "GET",
      ),
  };
};
