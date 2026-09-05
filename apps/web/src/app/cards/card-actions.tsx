"use client";

import { createApiClient } from "@cifra/api-client";
import { useState, type FormEvent } from "react";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function CardActions({
  token,
  cardId,
  invoiceId,
}: {
  token: string;
  cardId: string;
  invoiceId?: string;
}) {
  const api = createApiClient({ baseUrl: apiBaseUrl });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function purchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      await api.createCardPurchase(token, cardId, {
        idempotency_key: crypto.randomUUID(),
        amount_cents: Math.round(Number(data.get("amount")) * 100),
        purchase_date: String(data.get("date")),
        installments: Number(data.get("installments")),
        description: String(data.get("description")),
      });
      setMessage("Compra registrada com sucesso.");
      event.currentTarget.reset();
    } catch {
      setMessage("Não foi possível registrar a compra.");
    } finally {
      setBusy(false);
    }
  }

  async function pay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!invoiceId) return;
    setBusy(true);
    setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      await api.payInvoice(token, invoiceId, {
        payer_account_id: String(data.get("account")),
        idempotency_key: crypto.randomUUID(),
        amount_cents: Math.round(Number(data.get("amount")) * 100),
      });
      setMessage("Pagamento registrado com sucesso.");
      event.currentTarget.reset();
    } catch {
      setMessage("Não foi possível registrar o pagamento.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card-actions">
      <form onSubmit={purchase} aria-busy={busy}>
        <h2>Nova compra</h2>
        <label>
          Descrição
          <input name="description" required maxLength={500} />
        </label>
        <label>
          Valor
          <input name="amount" type="number" min="0.01" step="0.01" required />
        </label>
        <label>
          Data
          <input name="date" type="date" required />
        </label>
        <label>
          Parcelas
          <input name="installments" type="number" min="1" max="48" defaultValue="1" required />
        </label>
        <button disabled={busy}>{busy ? "Salvando..." : "Registrar compra"}</button>
      </form>
      {invoiceId ? (
        <form onSubmit={pay} aria-busy={busy}>
          <h2>Pagar fatura</h2>
          <label>
            ID da conta pagadora
            <input name="account" required />
          </label>
          <label>
            Valor
            <input name="amount" type="number" min="0.01" step="0.01" required />
          </label>
          <button disabled={busy}>{busy ? "Salvando..." : "Registrar pagamento"}</button>
        </form>
      ) : null}
      <p role="status" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
