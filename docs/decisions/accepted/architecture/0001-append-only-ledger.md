---
id: "0001"
title: Adotar ledger financeiro append-only
type: architecture
status: accepted
date: 2026-08-29
deciders: [Rhian Batista]
summary: Registrar correções financeiras por estorno e novo lançamento, preservando o histórico original.
tags: [finance, ledger, auditability, reconciliation]
relates_to: ["0003"]
supersedes:
superseded_by:
---

# 0001 — Adotar ledger financeiro append-only

## Context

O Cifra precisa apresentar saldos, faturas e orçamentos confiáveis. Atualizar ou apagar um lançamento financeiro em seu próprio registro destrói a origem do saldo e impede reconstruir o que ocorreu. Os extratos reais analisados incluem transferências entre conta e poupança, pagamentos por PIX e pagamento de fatura, todos dependentes de reconciliação.

A aplicação é multiusuário e terá importação de extratos. Erros de classificação, duplicação e edição retroativa são inevitáveis. O sistema precisa corrigir esses erros sem perder evidência.

## Decision

O Cifra registrará lançamentos financeiros em um ledger append-only lógico. Uma correção criará uma transação reversora vinculada ao lançamento original e, quando necessário, um novo lançamento correto. Saldos e totais serão derivados do ledger, não armazenados como valores mutáveis de autoridade.

## Rationale

Essa abordagem permite reconstrução, auditoria, idempotência e reconciliação contra extratos bancários. Também separa o histórico financeiro da apresentação simplificada da interface.

## Alternatives considered

| Option | Why not |
| :----- | :------ |
| Atualizar a linha original | Remove a evidência do valor anterior e dificulta auditoria e diagnóstico de divergências. |
| Soft delete sem reversão | Preserva a linha, mas não representa contabilmente a correção nem permite somas históricas consistentes. |
| Manter apenas snapshots de saldo | Não explica como o saldo foi formado e não suporta reconciliação por lançamento. |

## Consequences

**Positive**

- Todo saldo pode ser recalculado.
- Correções mantêm cadeia de evidência.
- Importações duplicadas podem ser identificadas sem sobrescrever dados.
- Pagamentos e estornos podem ser reconciliados.

**Negative / accepted costs**

- Consultas precisam considerar status e transações reversoras.
- A interface deve ocultar pares de correção na visão simplificada sem removê-los da auditoria.
- O volume de registros cresce, embora seja irrelevante para o uso pessoal previsto no MVP.

**Risks & open questions**

- A implementação deve impedir ciclos em `reverses_transaction_id`.
- Uma transação já revertida não pode ser revertida novamente sem regra explícita.
- Property tests devem verificar que o estorno restaura o saldo exato.

## References

- `docs/domain-validation-report.md`
- [`0003`](0003-optimistic-locking.md)
