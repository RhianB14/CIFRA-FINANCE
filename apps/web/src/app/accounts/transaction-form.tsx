"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { createApiClient } from "@cifra/api-client";

const apiBaseUrl =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const formSchema = z.object({
  amount: z
    .string()
    .min(1, "Valor é obrigatório")
    .regex(/^\d{1,3}(?:\.\d{3})*,\d{2}$/, "Informe o valor no formato 1.234,56"),
  description: z.string().min(1, "Descrição é obrigatória").max(500),
});

type FormValues = z.infer<typeof formSchema>;

const parseBrlAmountToCents = (value: string): number => {
  const normalized = value.replace(/\./g, "").replace(",", ".");
  return Math.round(Number(normalized) * 100);
};

const formatCentsAsBrl = (cents: number): string =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function TransactionForm({
  token,
  accountId,
}: {
  token: string;
  accountId: string;
  currency: string;
}) {
  const [balance, setBalance] = useState<number | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { amount: "", description: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    const api = createApiClient({ baseUrl: apiBaseUrl });
    try {
      const result = await api.createTransaction(token, accountId, {
        idempotency_key: crypto.randomUUID(),
        operation_type: "deposit",
        amount_cents: parseBrlAmountToCents(values.amount),
        occurred_at: new Date().toISOString(),
        description: values.description,
      });
      setBalance(result.current_balance_cents);
      reset();
    } catch {
      setSubmitError("Não foi possível registrar o lançamento");
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)}>
      <div>
        <label htmlFor="amount">Valor</label>
        <input id="amount" inputMode="decimal" {...register("amount")} />
        {errors.amount ? <span role="alert">{errors.amount.message}</span> : null}
      </div>
      <div>
        <label htmlFor="description">Descrição</label>
        <input id="description" {...register("description")} />
        {errors.description ? <span role="alert">{errors.description.message}</span> : null}
      </div>
      {submitError ? <p role="alert">{submitError}</p> : null}
      <button type="submit" disabled={isSubmitting}>
        Lançar
      </button>
      {balance !== null ? <p>Novo saldo: {formatCentsAsBrl(balance)}</p> : null}
    </form>
  );
}
