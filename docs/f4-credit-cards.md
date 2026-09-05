# F4 — Cartões de crédito, faturas e parcelamento

## Invariantes contábeis

- Valores são inteiros em centavos e a moeda do cartão coincide com a conta pagadora.
- Compra em cartão não altera saldo de conta bancária; aumenta a exposição do cartão.
- A fatura é materializada por cartão e competência, com unicidade `(card_id, year, month)`.
- Compra no dia do fechamento pertence à competência corrente; compra posterior pertence à próxima.
- Datas inexistentes são ajustadas para o último dia real do mês.
- Parcelas usam meses civis consecutivos. Centavos residuais são atribuídos às primeiras parcelas.
- O pagamento debita a conta pagadora e credita a conta técnica do cartão na mesma transação SQL.
- `paid_cents` deriva de `InvoicePayment` válidos; pagamentos são append-only.
- Compras e pagamentos possuem idempotência com conflito para payload diferente.
- Estornos adicionam lançamentos inversos e nunca apagam o histórico.
- Pagamento da fatura usa `operation_type=card_payment` e não entra novamente como consumo.

## Estados

Faturas abertas tornam-se `closed` no fechamento. Pagamento parcial produz `partially_paid`, quitação produz `paid` e vencimento sem quitação produz `overdue`. A derivação usa total de encargos e soma de pagamentos válidos.

## Job diário

O comando operacional permanece único:

```bash
python -m app.jobs
```

A saída JSON inclui `invoices_closed`. O advisory lock global impede duas instâncias de processarem simultaneamente. Falhas por cartão são isoladas e sanitizadas em `errors`.

## Oráculo e smoke

O oráculo versionado está em `docs/f4-accounting-oracle.json`. O smoke real executa:

```bash
SMOKE_BASE_URL=http://localhost:18000 python scripts/f4_smoke.py
```

`F4-SMOKE-OK` só é emitido após validar competências, exposição, limite disponível, parcelas exatas, idempotência e estorno parcelado append-only.
