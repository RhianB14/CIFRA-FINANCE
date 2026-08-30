---
id: "0003"
title: Aplicar optimistic locking em entidades mutáveis
type: architecture
status: accepted
date: 2026-08-29
deciders: [Rhian Batista]
summary: Exigir uma versão esperada nas alterações e devolver 409 quando o registro tiver sido modificado.
tags: [concurrency, data-integrity, api]
relates_to: ["0001", "0004"]
supersedes:
superseded_by:
---

# 0003 — Aplicar optimistic locking em entidades mutáveis

## Context

O Cifra terá clientes web e Android, inclusive com fila offline no mobile. Dois clientes podem editar uma conta, orçamento, cartão ou classificação de lançamento com base em versões diferentes. A última escrita silenciosa perderia a alteração anterior.

O ledger financeiro é append-only, mas metadados e configurações continuam mutáveis. A sincronização offline amplia a janela de conflito.

## Decision

Toda entidade mutável terá um campo inteiro `version`. Comandos de alteração enviarão a versão lida pelo cliente. A atualização será condicional à versão atual, incrementará o campo atomicamente e devolverá HTTP 409 com o estado atual quando houver conflito.

## Rationale

Optimistic locking é proporcional à baixa contenção esperada e detecta conflitos sem manter locks longos. O comportamento funciona tanto no web quanto na fila offline do mobile.

## Alternatives considered

| Option | Why not |
| :----- | :------ |
| Last-write-wins silencioso | Perde dados e mascara conflitos de sincronização. |
| Locks pessimistas | Exigem estado de sessão e expiração de locks; são excessivos para baixa contenção. |
| Comparar somente `updated_at` | Timestamps podem perder precisão ou sofrer diferenças de serialização; uma versão inteira é explícita. |

## Consequences

**Positive**

- Nenhuma alteração concorrente é perdida silenciosamente.
- O cliente pode apresentar o conflito e recarregar os dados.
- Testes conseguem reproduzir o conflito de forma determinística.

**Negative / accepted costs**

- Toda rota de atualização precisa transportar e validar `version`.
- O mobile precisa de uma política de resolução, inicialmente server-wins com aviso ao usuário.

**Risks & open questions**

- Operações compostas devem validar todas as versões antes do commit.
- Conflitos em classificação de transações importadas não podem alterar o ledger original.

## References

- [`0001`](0001-append-only-ledger.md)
- [`0004`](../security/0004-row-level-security.md)
