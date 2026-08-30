---
id: "0004"
title: Reforçar isolamento multiusuário com RLS
type: security
status: accepted
date: 2026-08-29
deciders: [Rhian Batista]
summary: Aplicar filtro de propriedade na aplicação e Row-Level Security no PostgreSQL para todas as tabelas do usuário.
tags: [security, multi-tenant, postgres, authorization]
relates_to: ["0003"]
supersedes:
superseded_by:
---

# 0004 — Reforçar isolamento multiusuário com RLS

## Context

O Cifra será multiusuário desde o início e armazenará dados financeiros sensíveis. Um filtro `user_id` esquecido em uma consulta poderia expor contas, transações, faturas ou anexos de outro usuário. Proteger apenas o router não cobre jobs, scripts, importadores e consultas futuras.

## Decision

Toda tabela pertencente a usuário terá `user_id` e Row-Level Security habilitada no PostgreSQL. Cada transação autenticada definirá `SET LOCAL app.current_user_id` com o usuário validado pelo JWT. A aplicação também aplicará escopo explícito por usuário e responderá 404 para recursos de outro proprietário.

## Rationale

A autorização em duas camadas reduz o impacto de uma consulta incorreta. `SET LOCAL` limita o contexto à transação e evita vazar identidade entre conexões reutilizadas pelo pool.

## Alternatives considered

| Option | Why not |
| :----- | :------ |
| Filtrar somente na aplicação | Um único filtro esquecido cria vazamento entre usuários. |
| Um schema PostgreSQL por usuário | Complexidade operacional desproporcional ao produto e número de usuários. |
| Um banco por usuário | Migrações, pooling e operação seriam excessivamente caros. |

## Consequences

**Positive**

- Consultas sem contexto não retornam dados do usuário.
- Jobs e importadores recebem a mesma barreira de isolamento.
- Testes de usuário B contra recurso A podem provar defesa em profundidade.

**Negative / accepted costs**

- Migrações precisam criar e testar policies.
- Conexões administrativas exigem um caminho separado, auditado e restrito.
- O pool precisa garantir que o contexto nunca sobreviva ao fim da transação.

**Risks & open questions**

- Tabelas globais precisam ser explicitamente listadas e não podem herdar policy de usuário por engano.
- Exclusão LGPD e jobs de manutenção exigem papel administrativo mínimo.
- Todo teste de integração deve confirmar o valor de `app.current_user_id` dentro da transação.

## References

- [`0003`](../architecture/0003-optimistic-locking.md)
- `docs/domain-validation-report.md`
