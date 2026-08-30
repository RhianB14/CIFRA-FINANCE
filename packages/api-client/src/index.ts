import type { LiveStatus, ReadyStatus } from "@cifra/shared-types";

export type ApiClientOptions = {
  baseUrl: string;
  request?: typeof fetch;
};

export type CifraApiClient = {
  live: () => Promise<LiveStatus>;
  ready: () => Promise<ReadyStatus>;
};

const requestJson = async <T>(request: typeof fetch, url: string): Promise<T> => {
  const response = await request(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Cifra API request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
};

export const createApiClient = ({ baseUrl, request = fetch }: ApiClientOptions): CifraApiClient => {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "");
  return {
    live: () => requestJson<LiveStatus>(request, `${normalizedBaseUrl}/health/live`),
    ready: () => requestJson<ReadyStatus>(request, `${normalizedBaseUrl}/health/ready`),
  };
};
