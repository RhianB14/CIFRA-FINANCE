import { createApiClient, type CardInvoice } from "@cifra/api-client";
import { redirect } from "next/navigation";

import CardActions from "./card-actions";

const apiBaseUrl =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const dynamic = "force-dynamic";

type SearchParams = Promise<{ token?: string }>;

const money = (cents: number, currency: string) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency });
const invoiceLabel = (invoice: CardInvoice) =>
  `${String(invoice.month).padStart(2, "0")}/${invoice.year}`;

export default async function CardsPage({ searchParams }: { searchParams: SearchParams }) {
  const { token } = await searchParams;
  if (!token) redirect("/");
  const api = createApiClient({ baseUrl: apiBaseUrl });
  const cards = await api.listCards(token).catch(() => []);
  const cardsWithData = await Promise.all(
    cards.map(async (card) => ({
      card,
      exposure: await api.cardExposure(token, card.id).catch(() => null),
      invoices: await api.listInvoices(token, card.id).catch(() => []),
    })),
  );

  return (
    <main className="cards-page">
      <header>
        <h1>Cartões de crédito</h1>
        <p>Acompanhe limite, exposição, faturas e parcelas.</p>
      </header>
      {cardsWithData.length === 0 ? (
        <section>
          <h2>Nenhum cartão</h2>
          <p>Cadastre seu primeiro cartão pela API para começar.</p>
        </section>
      ) : null}
      {cardsWithData.map(({ card, exposure, invoices }) => {
        const open = invoices.find((invoice) => invoice.status === "open");
        return (
          <section key={card.id} aria-label={`Cartão ${card.name}`}>
            <div className="card-title">
              <h2>{card.name}</h2>
              <span>{card.archived_at ? "Arquivado" : "Ativo"}</span>
            </div>
            <p>{card.last_four ? `Final ${card.last_four}` : "Número não armazenado"}</p>
            <dl className="card-metrics">
              <div>
                <dt>Limite</dt>
                <dd>{money(card.limit_cents, card.currency)}</dd>
              </div>
              <div>
                <dt>Comprometido</dt>
                <dd>{exposure ? money(exposure.exposure_cents, card.currency) : "Indisponível"}</dd>
              </div>
              <div>
                <dt>Disponível</dt>
                <dd>
                  {exposure ? money(exposure.available_cents, card.currency) : "Indisponível"}
                </dd>
              </div>
            </dl>
            <h3>Faturas anteriores e próximas</h3>
            {invoices.length === 0 ? (
              <p>Nenhuma fatura materializada.</p>
            ) : (
              <ul className="invoice-list">
                {invoices.map((invoice) => (
                  <li key={invoice.id}>
                    <strong>{invoiceLabel(invoice)}</strong>
                    <span>{invoice.status.replace("partially_paid", "parcialmente paga")}</span>
                    <span>
                      {money(invoice.total_cents, card.currency)} · pago{" "}
                      {money(invoice.paid_cents, card.currency)} · restante{" "}
                      {money(invoice.remaining_cents, card.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {!card.archived_at ? (
              <CardActions token={token} cardId={card.id} invoiceId={open?.id} />
            ) : null}
          </section>
        );
      })}
    </main>
  );
}
