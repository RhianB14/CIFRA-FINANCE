---
id: "0002"
title: Registrar moeda em cada conta e lançamento
type: architecture
status: accepted
date: 2026-08-29
deciders: [Rhian Batista]
summary: Armazenar moeda ISO 4217 por conta e lançamento, mantendo BRL como única moeda operacional no MVP.
tags: [finance, currency, data-model]
relates_to: ["0001"]
supersedes:
superseded_by:
---

# 0002 — Registrar moeda em cada conta e lançamento

## Context

O MVP operará em BRL, mas adicionar a coluna de moeda posteriormente exigiria migrar contas, transações, faturas, orçamentos e agregações já existentes. Valores monetários não podem usar ponto flutuante. A amostra real analisada está integralmente em reais e valida o uso de centavos inteiros.

## Decision

Cada conta e lançamento armazenará um código de moeda ISO 4217. O MVP aceitará somente `BRL` nas operações de usuário e armazenará valores em centavos inteiros com `BIGINT`. Transferências entre moedas diferentes serão rejeitadas até existir uma decisão específica sobre conversão e câmbio.

## Rationale

A coluna evita uma migração estrutural cara sem introduzir a complexidade funcional de multi-moeda no MVP. Restringir operações a BRL mantém cálculos, relatórios e reconciliação determinísticos.

## Alternatives considered

| Option | Why not |
| :----- | :------ |
| Não armazenar moeda | Pressupõe implicitamente BRL e torna futura migração ampla e arriscada. |
| Implementar multi-moeda completa no MVP | Exige fontes de câmbio, competência de cotação, ganhos cambiais e consolidação; não há requisito atual. |
| Usar decimal genérico | Valores brasileiros em centavos cabem em `BIGINT`; inteiros reduzem ambiguidade de arredondamento. |

## Consequences

**Positive**

- Todos os valores têm unidade explícita.
- O modelo fica preparado para evolução sem prometer multi-moeda funcional.
- Cálculos em centavos permanecem exatos.

**Negative / accepted costs**

- A moeda aparece em tabelas mesmo sendo constante no MVP.
- Validação precisa rejeitar códigos diferentes de BRL até a funcionalidade existir.

**Risks & open questions**

- Orçamentos e faturas precisam herdar ou validar a moeda da conta/cartão associado.
- Uma futura conversão exigirá novo ADR com fonte e momento da cotação.

## References

- `docs/domain-validation-report.md`
- [`0001`](0001-append-only-ledger.md)
