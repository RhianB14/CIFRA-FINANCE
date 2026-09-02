import { redirect } from "next/navigation";
import { createApiClient } from "@cifra/api-client";

const apiBaseUrl =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ token?: string }>;

export default async function AccountsPage({ searchParams }: { searchParams: SearchParams }) {
  const { token } = await searchParams;
  if (!token) {
    redirect("/");
  }
  const api = createApiClient({ baseUrl: apiBaseUrl });
  const accounts = await api.listAccounts(token).catch(() => []);

  return (
    <main>
      <section>
        <h1>Contas</h1>
        <ul>
          {accounts.map((account) => (
            <li key={account.id}>
              <span>{account.name}</span>
              <span>
                {(account.current_balance_cents / 100).toLocaleString("pt-BR", {
                  style: "currency",
                  currency: account.currency,
                })}
              </span>
              <span>{account.archived ? "arquivada" : "ativa"}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
