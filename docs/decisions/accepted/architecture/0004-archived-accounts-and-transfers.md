---
id: "0004"
title: Definir semântica de contas arquivadas e classificação de transferências
type: architecture
status: accepted
date: 2026-09-03
deciders: [Rhian Batista]
summary: Conta arquivada sai do dashboard a partir do arquivamento; transferências internas não contam como receita/despesa; transferência exige moedas iguais.
tags: [finance, dashboard, transfers, archiving]
relates_to: ["0001", "0002"]
supersedes:
superseded_by:
---

# 0004 — Semântica de contas arquivadas e classificação de transferências

## Context

O dashboard consolidava saldos apenas de contas ativas, mas os agregados de fluxo
(income/expense) consultavam transações de todas as contas, incluindo arquivadas.
Além do risco de KeyError em moedas que só existiam em contas arquivadas, o usuário
não conseguia prever o que o dashboard mostrava após arquivar. Em paralelo, as pernas
`transfer_in`/`transfer_out` podiam inflar receita e despesa do mês.

## Decision

1. **Conta arquivada** (`archived_at` definido): deixa de aparecer em `accounts`,
   `consolidated_by_currency`, `month_flow`, `evolution`, `month-comparison`,
   `upcoming` e `recent` a partir do arquivamento, em qualquer moeda. Ou seja,
   `upcoming` e `recent` refletem apenas lançamentos de contas ativas; lançamentos
   históricos permanecem no ledger (append-only) e nas listas de transações por
   conta; a conta pode ser desarquivada, e todo o histórico volta a aparecer no
   dashboard imediatamente.
2. **Transferências internas**: pernas `transfer_in`/`transfer_out` entre contas do
   mesmo usuário são sempre excluídas de income/expense; afetam apenas saldos por
   conta/moeda e a evolução (via net movement, quando permanecerem ativas).
3. **Moeda da transferência**: por ADR 0002, transferências entre contas de moedas
   diferentes são rejeitadas com 422 até existir decisão específica de câmbio.

## Rationale

Arquivar é um gesto de organização, não de apagamento: o ledger permanece íntegro e a
conta pode retornar. O dashboard deve refletir exatamente o conjunto de contas que o
usuário está gerindo ativamente. Transferências não são resultado econômico — tratá-las
como receita/despesa infla indicadores sem qualquer movimento real de patrimônio.

## Alternatives considered

| Option | Why not |
| :----- | :------ |
| Manter fluxo de arquivadas no dashboard | Imprevisível para o usuário e fonte de KeyError em moedas órfãs. |
| Excluir transações de arquivadas do ledger | Violaria o append-only (ADR 0001). |
| Contar transferência como receita e despesa | Infla ambos sem mudança patrimonial. |

## Consequences

**Positive**

- Dashboard determinístico e previsível após arquivamento.
- Nenhum 500/KeyError possível por moeda órfã.
- Indicadores de receita/despesa refletem apenas atividade econômica real.

**Negative / accepted costs**

- O histórico de uma conta arquivada não aparece nos agregados até a conta ser
  desarquivada (documentado aqui).

**Risks & open questions**

- Relatórios futuros de "histórico total" devem consultar o ledger diretamente, com
  escopo explícito sobre contas arquivadas.

## References

- [`0001`](0001-append-only-ledger.md)
- [`0002`](0002-currency-per-account.md)
- `apps/api/tests/integration/test_dashboard_archived_and_transfers.py`
