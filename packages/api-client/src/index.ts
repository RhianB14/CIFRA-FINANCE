import type { LiveStatus, ReadyStatus } from "@cifra/shared-types";

export type ApiClientOptions = {
  baseUrl: string;
  request?: typeof fetch;
  token?: string;
};

export type CreditCard = {
  id: string;
  account_id: string;
  name: string;
  currency: string;
  limit_cents: number;
  closing_day: number;
  due_day: number;
  last_four: string | null;
  version: number;
  archived_at: string | null;
};

export type CardCreateInput = {
  name: string;
  currency: string;
  limit_cents: number;
  closing_day: number;
  due_day: number;
  last_four?: string;
};

export type CardPatchInput = Partial<
  Pick<CardCreateInput, "name" | "limit_cents" | "closing_day" | "due_day">
> & {
  expected_version: number;
};

export type CardExposure = {
  exposure_cents: number;
  limit_cents: number;
  available_cents: number;
};

export type CardInvoice = {
  id: string;
  card_id: string;
  year: number;
  month: number;
  status: "open" | "closed" | "partially_paid" | "paid" | "overdue";
  due_date: string | null;
  closed_at: string | null;
  total_cents: number;
  paid_cents: number;
  remaining_cents: number;
};

export type CardTransaction = {
  id: string;
  account_id: string;
  amount_cents: number;
  kind: string;
  operation_type: string;
  status: string;
  occurred_at: string;
  description: string | null;
  charge_kind: string | null;
  installment_group_id: string | null;
  installment_number: number | null;
  installment_total: number | null;
  result_balance_after_cents: number;
  result_balance_version: number;
};

export type CardPurchaseInput = {
  idempotency_key: string;
  amount_cents: number;
  purchase_date: string;
  installments: number;
  description?: string;
  category_id?: string;
  charge_kind?: "purchase" | "interest" | "late_fee" | "iof" | "withdrawal_fee" | "other";
};

export type InvoicePayment = {
  id: string;
  invoice_id: string;
  transaction_id: string;
  amount_cents: number;
  kind: "payment" | "reversal";
  reversed_by_id: string | null;
};

export type InvoicePaymentInput = {
  payer_account_id: string;
  idempotency_key: string;
  amount_cents: number;
  occurred_at?: string;
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

export type RecentItem = UpcomingItem;

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
  listCards: (token: string) => Promise<CreditCard[]>;
  getCard: (token: string, id: string) => Promise<CreditCard>;
  createCard: (token: string, input: CardCreateInput) => Promise<CreditCard>;
  updateCard: (token: string, id: string, input: CardPatchInput) => Promise<CreditCard>;
  archiveCard: (token: string, id: string, expectedVersion: number) => Promise<void>;
  cardExposure: (token: string, id: string) => Promise<CardExposure>;
  listInvoices: (token: string, cardId: string) => Promise<CardInvoice[]>;
  getInvoice: (token: string, invoiceId: string) => Promise<CardInvoice>;
  invoiceCharges: (token: string, invoiceId: string) => Promise<CardTransaction[]>;
  createCardPurchase: (
    token: string,
    cardId: string,
    input: CardPurchaseInput,
  ) => Promise<CardTransaction[]>;
  payInvoice: (
    token: string,
    invoiceId: string,
    input: InvoicePaymentInput,
  ) => Promise<InvoicePayment>;
  reversePurchase: (
    token: string,
    transactionId: string,
    idempotencyKey: string,
  ) => Promise<CardTransaction[]>;
  dashboardSummary: (token: string, month?: string) => Promise<DashboardSummary>;
  dashboardEvolution: (token: string, months: number, until?: string) => Promise<EvolutionPoint[]>;
  dashboardMonthComparison: (token: string, month?: string) => Promise<MonthComparison>;
};

const requestJson = async <T>(request: typeof fetch, url: string): Promise<T> => {
  const response = await request(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Cifra API request failed with status ${response.status}`);
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
  if (!response.ok) throw new Error(`Cifra API request failed with status ${response.status}`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
};

export const createApiClient = ({ baseUrl, request = fetch }: ApiClientOptions): CifraApiClient => {
  const root = baseUrl.replace(/\/$/, "");
  return {
    live: () => requestJson<LiveStatus>(request, `${root}/health/live`),
    ready: () => requestJson<ReadyStatus>(request, `${root}/health/ready`),
    listAccounts: (token) => authedJson(request, `${root}/accounts`, token, "GET"),
    createAccount: (token, input) => authedJson(request, `${root}/accounts`, token, "POST", input),
    updateAccount: (token, id, input) =>
      authedJson(request, `${root}/accounts/${id}`, token, "PATCH", input),
    deleteAccount: (token, id) => authedJson(request, `${root}/accounts/${id}`, token, "DELETE"),
    createTransaction: (token, id, input) =>
      authedJson(request, `${root}/accounts/${id}/transactions`, token, "POST", input),
    listCards: (token) => authedJson(request, `${root}/cards`, token, "GET"),
    getCard: (token, id) => authedJson(request, `${root}/cards/${id}`, token, "GET"),
    createCard: (token, input) => authedJson(request, `${root}/cards`, token, "POST", input),
    updateCard: (token, id, input) =>
      authedJson(request, `${root}/cards/${id}`, token, "PATCH", input),
    archiveCard: (token, id, expectedVersion) =>
      authedJson(request, `${root}/cards/${id}`, token, "DELETE", {
        expected_version: expectedVersion,
      }),
    cardExposure: (token, id) => authedJson(request, `${root}/cards/${id}/exposure`, token, "GET"),
    listInvoices: (token, cardId) =>
      authedJson(request, `${root}/cards/${cardId}/invoices`, token, "GET"),
    getInvoice: (token, id) => authedJson(request, `${root}/cards/invoices/${id}`, token, "GET"),
    invoiceCharges: (token, id) =>
      authedJson(request, `${root}/cards/invoices/${id}/charges`, token, "GET"),
    createCardPurchase: (token, id, input) =>
      authedJson(request, `${root}/cards/${id}/purchases`, token, "POST", input),
    payInvoice: (token, id, input) =>
      authedJson(request, `${root}/cards/invoices/${id}/payments`, token, "POST", input),
    reversePurchase: (token, id, key) =>
      authedJson(request, `${root}/cards/purchases/${id}/reversal`, token, "POST", {
        idempotency_key: key,
      }),
    dashboardSummary: (token, month) =>
      authedJson(
        request,
        month
          ? `${root}/dashboard/summary?month=${encodeURIComponent(month)}`
          : `${root}/dashboard/summary`,
        token,
        "GET",
      ),
    dashboardEvolution: (token, months, until) => {
      const params = new URLSearchParams({ months: String(months) });
      if (until) params.set("until", until);
      return authedJson(request, `${root}/dashboard/evolution?${params.toString()}`, token, "GET");
    },
    dashboardMonthComparison: (token, month) =>
      authedJson(
        request,
        month
          ? `${root}/dashboard/month-comparison?month=${encodeURIComponent(month)}`
          : `${root}/dashboard/month-comparison`,
        token,
        "GET",
      ),
  };
};
