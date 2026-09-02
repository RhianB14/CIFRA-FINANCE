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

export type CifraApiClient = {
  live: () => Promise<LiveStatus>;
  ready: () => Promise<ReadyStatus>;
  listAccounts: (token: string) => Promise<Account[]>;
  createAccount: (token: string, input: AccountInput) => Promise<Account>;
  updateAccount: (token: string, id: string, patch: AccountPatchInput) => Promise<Account>;
  deleteAccount: (token: string, id: string) => Promise<void>;
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
  };
};
