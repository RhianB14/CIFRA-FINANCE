# FINANCE PROJ — Plano Mestre v2 (App Android + Web de Controle Financeiro)

> **For Hermes:** Usar o skill `subagent-driven-development` para executar fase a fase, task a task. Cada fase termina com **critérios de aceite verificáveis** antes de avançar. Toda fase que toca domínio termina com teste de reconciliação; toda fase que toca API entra sob CI verde.

**Data:** 2026-08-29 · **Versão:** 2.1 · **Origem:** revisão profissional do plano v1 (2026-08-29 14:34) incorporando gaps de domínio (BR), segurança, observabilidade, CI/CD, LGPD, offline mobile e testes. v2.1 (2026-08-29): correções da auditoria documental pré-F0 (exemplo contábil da F2, esqueleto mobile na F0, importação idempotente na F2, package Android, rollover, referência oficial aos ADRs 0001–0004).

**Mudanças-chave vs v1:**
- Domínio: parcelamento de cartão, `card_invoices` como tabela real, recorrências, agendados, anexos, tags, RLS multi-tenant, `updated_at`/`version` para optimistic locking, moeda por conta.
- Segurança: 2FA/TOTP, rate limit e audit log desde a Fase 1, refresh rotation com reuse detection, biometria mobile, argon2id.
- Novas fases: **0.5 CI/CD e Qualidade**, **1.5 Segurança de Base**, **6.5 Observabilidade**, **7.5 LGPD**.
- Testes: property-based (`hypothesis`), E2E obrigatório (Playwright + Maestro), coverage threshold numérico, contract tests.
- Mobile offline-first com SQLite local + fila de mutations.
- Documentação: ADRs, C4, OpenAPI versionado, runbook operacional.

---

## Goal

Construir um app de **controle financeiro pessoal** com **Android (Expo/React Native + TypeScript)** e **web (Next.js + TypeScript)**, compartilhando um único **backend FastAPI + PostgreSQL + Docker** com **auth JWT + 2FA multi-usuário desde o dia 1**. Núcleo MVP: contas, lançamentos, transferências, saldo, **orçamentos por categoria com alertas**, **cartões de crédito com faturas, fechamento e parcelamento**, **recorrências e agendados**, **anexos e tags**, **modo offline no mobile**.

## Current context / assumptions

- **Estado atual (2026-08-29):** Pre-0 concluído — decisões fechadas (7/8, domínio adiado), schema validado com dataset real de lançamentos (≥30, detalhes no relatório anonimizado), ADRs 0001–0004 aceitos em `docs/decisions/`, ambiente local completo verificado. O projeto ainda **não possui implementação** da aplicação; a F0 cria a primeira.
- Stack e padrões herdados do SharkTrack (FastAPI, Docker, Next.js, pnpm, TDD, service layer puro).
- Dev no Windows + Docker Desktop; testes backend com pytest; monorepo com pnpm workspaces + Turborepo.
- Sem integração bancária automática no MVP — automações e Open Finance permanecem pós-MVP. **Importação manual de CSV é escopo da F2** (exigência da validação com dados reais: idempotência por SHA-256/`external_id`/fingerprint, reconciliação por snapshots e fila "A classificar"). OFX e integrações automáticas ficam pós-MVP.
- Idioma da UI: pt-BR. Moeda padrão: BRL. **Armazenar em centavos, `BigInteger`, nunca float.** Campo `currency` existe por conta desde o MVP para não travar multi-moeda futura.
- Timestamps: sempre `TIMESTAMPTZ` em UTC; UI converte para America/Sao_Paulo.

## Tech Stack

| Camada | Escolha |
|---|---|
| Mobile | Expo (React Native) + TypeScript, Expo Router, expo-sqlite (offline), expo-secure-store, expo-local-authentication (biometria) |
| Web | Next.js (App Router) + TypeScript + Tailwind + TanStack Query |
| Backend | FastAPI + SQLAlchemy 2.0 (async) + Alembic + Pydantic v2 |
| Banco | PostgreSQL 16 com **Row-Level Security** habilitada |
| Cache/fila | Redis (rate limit, jti revogados, jobs) |
| Storage | MinIO (dev) / S3-compat (prod) para anexos |
| Auth | JWT (access + refresh com rotation + reuse detection), **argon2id** via `passlib`, TOTP 2FA (`pyotp`) |
| Infra | Docker Compose (db + redis + minio + api + web) |
| Observabilidade | structlog (JSON) + Sentry + Prometheus + Grafana (opcional) |
| Testes | pytest + httpx + **hypothesis** (backend), Vitest/Testing Library (web), **Playwright** (E2E web), **Maestro** (E2E mobile) |
| Qualidade | ruff + mypy strict + eslint + prettier + pre-commit + commitlint |
| Monorepo | pnpm workspaces + Turborepo |

---

## Arquitetura e layout do repositório

```
FINANCE PROJ/
├── apps/
│   ├── api/            # FastAPI (Python 3.11)
│   │   ├── app/
│   │   │   ├── core/           # settings, security (JWT, 2FA), deps, ratelimit
│   │   │   ├── db/             # session, base, seeds, RLS helpers
│   │   │   ├── models/         # SQLAlchemy (com updated_at, version, RLS)
│   │   │   ├── schemas/        # Pydantic v2 (In/Out separados — anti mass-assignment)
│   │   │   ├── routers/        # auth, accounts, transactions, cards, invoices, budgets, recurring, attachments, audit, gdpr
│   │   │   ├── services/       # regras de negócio (saldo, fatura, alertas, parcelas, recorrência)
│   │   │   ├── jobs/           # recorrência diária, geração de fatura, backup verify
│   │   │   └── telemetry/      # structlog, sentry, prometheus
│   │   ├── alembic/            # migrações reversíveis
│   │   ├── tests/
│   │   │   ├── unit/           # services puros + hypothesis
│   │   │   ├── integration/    # routers via AsyncClient
│   │   │   ├── security/       # scope isolation, RLS, replay, brute force
│   │   │   └── property/       # invariantes contábeis (hypothesis)
│   │   ├── pyproject.toml
│   │   └── Dockerfile          # multi-stage
│   ├── web/            # Next.js
│   │   ├── src/app/            # (auth), (dashboard): contas, cartões, orçamentos, recorrências
│   │   ├── e2e/                # Playwright
│   │   └── Dockerfile
│   └── mobile/         # Expo
│       ├── app/                # expo-router
│       ├── src/db/             # SQLite local + fila de sync (F6)
│       └── .maestro/           # flows E2E (F6)
├── packages/
│   ├── shared-types/   # tipos TS + zod schemas (fonte da verdade)
│   ├── api-client/     # cliente HTTP tipado (interceptor de auth, refresh, retry)
│   └── domain-rules/   # regras puras compartilhadas (ex.: cálculo de fatura previewado no cliente)
├── docs/
│   ├── decisions/      # ADRs — registry gerido por scripts/decisions.py; aceitos em accepted/
│   ├── architecture/   # C4 (context, container, component)
│   ├── api/            # openapi.yaml versionado
│   ├── runbook/        # restore-db.md, rotate-secrets.md, incident.md
│   ├── privacy/        # policy pt-BR, terms, LGPD map
│   └── decisions.md
├── .github/workflows/  # ci, security-scan, release
├── docker-compose.yml
├── docker-compose.prod.yml
├── turbo.json
├── pnpm-workspace.yaml
├── .pre-commit-config.yaml
├── CONTRIBUTING.md
├── CHANGELOG.md
└── README.md
```

**Regras de ouro:**
1. Web e mobile **nunca** chamam a API com fetch cru — sempre via `packages/api-client`.
2. Tipos e validação vivem em `packages/shared-types` (zod → TS types → schema OpenAPI conferido em CI).
3. **Cálculo de domínio (saldo, fatura, orçamento) só no `services/`** — proibido em router, template ou cliente.
4. **Nenhum acesso a DB sem filtro `user_id`** — reforçado por RLS no Postgres.

---

## Modelo de dados (fonte da verdade do domínio)

```sql
-- Toda tabela mutável tem: id UUID PK, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, version INT
-- RLS habilitada em toda tabela com user_id; policy: user_id = current_setting('app.current_user_id')::uuid

users                (id UUID PK, email UNIQUE, password_hash /* argon2id */,
                      name, totp_secret NULL, totp_enabled BOOL, locale, created_at, updated_at)

refresh_tokens       (id UUID PK, user_id FK, jti UNIQUE, device_label,
                      issued_at, expires_at, revoked_at NULL, replaced_by FK NULL)  -- rotation + reuse detection

audit_events         (id UUID PK, user_id FK NULL, actor_ip, event_type, entity_type, entity_id,
                      before JSONB NULL, after JSONB NULL, occurred_at)  -- append-only

accounts             (id, user_id, name, type: checking|savings|cash|wallet|investment,
                      currency CHAR(3) DEFAULT 'BRL', initial_balance_cents BIGINT,
                      archived BOOL, updated_at, version)

import_batches       (id, user_id, source_type, source_name, source_sha256 UNIQUE,
                      period_start DATE NULL, period_end DATE NULL,
                      status: pending|processed|failed, imported_at)

account_balance_snapshots (id, user_id, account_id FK, import_batch_id FK NULL,
                           observed_at TIMESTAMPTZ, balance_cents BIGINT,
                           UNIQUE(account_id, observed_at, import_batch_id))

categories           (id, user_id, name, kind: expense|income|neutral, color, icon,
                      parent_id FK NULL /* hierarquia */, archived, updated_at, version)

tags                 (id, user_id, name, color)
transaction_tags     (transaction_id FK, tag_id FK, PK composto)

credit_cards         (id, user_id, name, brand, last_four,
                      limit_cents BIGINT, closing_day SMALLINT, due_day SMALLINT,
                      account_id FK /* conta que paga por padrão */, archived, updated_at, version)

card_invoices        (id, user_id, credit_card_id FK,
                      period_start DATE, period_end DATE, closing_date DATE, due_date DATE,
                      status: open|closed|paid|partially_paid|overdue,
                      total_cents BIGINT, paid_cents BIGINT,
                      created_at, updated_at, version,
                      UNIQUE(credit_card_id, period_start))  -- materializada, idempotente

transactions         (id, user_id,
                      account_id FK NULL, credit_card_id FK NULL, card_invoice_id FK NULL,
                      category_id FK NULL /* NULL em transferências */,
                      description, amount_cents BIGINT (sinalizado), currency CHAR(3),
                      type: income|expense|transfer_out|transfer_in|card_charge|card_payment|adjustment,
                      status: pending|posted|canceled,      -- agendados usam pending
                      date DATE, posted_at TIMESTAMPTZ NULL,
                      transfer_group_id UUID NULL,
                      installment_group_id UUID NULL, installment_number SMALLINT NULL,
                      installment_total SMALLINT NULL,
                      reverses_transaction_id FK NULL,
                      recurring_id FK NULL,
                      import_batch_id FK NULL, external_id VARCHAR NULL,
                      raw_description VARCHAR NULL, source_document_number VARCHAR NULL,
                      import_fingerprint CHAR(64) NULL,
                      card_charge_kind: purchase|interest|late_fee|iof|withdrawal_fee|other NULL,
                      created_at, updated_at, version)

invoice_payments     (id, user_id, card_invoice_id FK, account_transaction_id FK,
                      amount_cents BIGINT, status: posted|reversed,
                      reverses_payment_id FK NULL, paid_at TIMESTAMPTZ,
                      created_at)

recurring_transactions (id, user_id, template JSONB, cadence: daily|weekly|monthly|yearly,
                        day_of_month SMALLINT NULL, weekday SMALLINT NULL,
                        starts_on DATE, ends_on DATE NULL, next_run_on DATE,
                        active BOOL, updated_at, version)

budgets              (id, user_id, category_id FK, month DATE (1º dia),
                      limit_cents BIGINT, rollover BOOL DEFAULT false,
                      updated_at, version,
                      UNIQUE(user_id, category_id, month))

transaction_attachments (id, user_id, transaction_id FK, storage_key, filename,
                         mime, size_bytes, sha256, uploaded_at)

-- Índices críticos
CREATE INDEX ix_tx_user_date        ON transactions (user_id, date DESC);
CREATE INDEX ix_tx_user_acc_date    ON transactions (user_id, account_id, date DESC);
CREATE INDEX ix_tx_user_card_date   ON transactions (user_id, credit_card_id, date DESC);
CREATE INDEX ix_tx_invoice          ON transactions (card_invoice_id) WHERE card_invoice_id IS NOT NULL;
CREATE INDEX ix_tx_installment      ON transactions (installment_group_id) WHERE installment_group_id IS NOT NULL;
CREATE UNIQUE INDEX ux_tx_import_external ON transactions (user_id, import_batch_id, external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX ux_tx_import_fingerprint ON transactions (user_id, import_batch_id, import_fingerprint) WHERE import_fingerprint IS NOT NULL;
CREATE INDEX ix_snapshot_account_time ON account_balance_snapshots (account_id, observed_at DESC);
CREATE INDEX ix_invoice_payment       ON invoice_payments (card_invoice_id, paid_at);
CREATE INDEX ix_recur_next          ON recurring_transactions (next_run_on) WHERE active;
```

**Decisões contábeis (ledger confiável, separação saldo/exposição/lucro):**

1. **Saldo de conta = `initial_balance_cents` + Σ(transactions POSTED da conta)** — nunca campo mutável. Recalculável a qualquer momento (reconciliação).
2. **Saldo projetado** = saldo atual + Σ(transactions PENDING até data D). Endpoint separado.
3. **Transferência** = 2 transações (out na origem, in no destino) unidas por `transfer_group_id`, `category_id = NULL`, atômicas via `BEGIN...COMMIT`.
4. **Compra no cartão** NÃO baixa saldo de conta. Baixa na **fatura** materializada (`card_invoices`). Fechamento gera fatura idempotente (rerun não duplica).
5. **Parcelamento**: compra 3x gera **3 transações** ligadas por `installment_group_id`, distribuídas em 3 faturas consecutivas a partir do fechamento aplicável.
6. **Exposição do cartão** = Σ(compras em faturas OPEN + CLOSED não pagas). **Saldo ≠ Exposição** — relatório mostra ambos.
7. **`card_payment`** = transfer_out da conta + registro append-only em `invoice_payments`. `paid_cents` é derivado da soma dos pagamentos válidos; cache materializado, se usado, é reconciliável. Pagamento parcial permitido; status vai a `partially_paid` ou `paid`.
8. **Importação idempotente**: cada arquivo gera `import_batches.source_sha256`; transações usam `external_id` quando disponível e fingerprint determinístico como fallback. Reimportar a mesma fonte não duplica lançamentos.
9. **Conciliação bancária**: `account_balance_snapshots` guarda os saldos declarados pelo banco em pontos temporais. O saldo derivado do ledger precisa bater com o snapshot correspondente.
10. **Classificação pendente**: `category_id=NULL` representa "A classificar". Descrição genérica, como PIX QR Code, nunca recebe categoria inventada sem evidência.
11. **Encargos de cartão**: `card_charge_kind` distingue compra, juros, multa, IOF, tarifa de saque e outros encargos sem inflar o enum principal.
12. **Orçamento** compara Σ(despesas POSTED do mês por categoria) vs `limit_cents`. Alertas: ≥80% (`warning`), ≥100% (`over_budget`). `rollover=true` soma sobra do mês anterior.
13. **Estorno** = nova transação com `reverses_transaction_id` apontando para a original. UI de "extrato limpo" filtra pares. Auditoria vê tudo.
14. **Optimistic locking**: toda edição envia `version`; conflito devolve **409** com diff.

---

## Fases

### Fase 0 — Fundação (monorepo + infra) · ~1 sessão (3h)

Init do monorepo, Docker Compose, "hello" de cada app. **Os ADRs 0001–0004 já existem** (promovidos na Pre-0 em `docs/decisions/accepted/`) — a F0 apenas os versiona no primeiro commit; nada de ADR duplicado.

- [x] `git init` + `.gitignore` (node, python, .env, .expo, .venv, `imports/`)
- [x] pnpm workspace + turbo + `apps/web` (Next App Router, TS, Tailwind) + `packages/shared-types` + `packages/api-client` + `packages/domain-rules` (esqueleto)
- [x] `apps/mobile`: **esqueleto mínimo funcional** — Expo + Expo Router + TypeScript, tela inicial identificando o Cifra, dependência de `packages/api-client` preparada, passando typecheck; implementação completa (offline, biometria, telas financeiras) continua reservada à F6
- [x] `apps/api`: FastAPI mínimo com `/health/live` e `/health/ready`, `pyproject.toml` com uv, pytest passando
- [x] `docker-compose.yml`: postgres:16 + redis:7 + minio + api (uvicorn --reload) + web; volumes nomeados
- [x] `README.md` com comandos; `docs/architecture/c4-context.md` esboço
- **Aceite:** `docker compose up` sobe db+redis+minio+api+web; `/health/ready` responde 200 com dependências verificadas de verdade; `pnpm dev` roda web e mobile sem erro de tipos (mobile coberto por typecheck/expo config validation); ADRs 0001–0004 commitados no primeiro commit; `imports/` e `.env` ignorados pelo Git.

### Fase 0.5 — CI/CD e Qualidade · ~1 sessão (3h) — **NOVA**

Rede de segurança antes de tocar em domínio.

- [ ] `.pre-commit-config.yaml`: ruff (lint + format), mypy `--strict`, eslint, prettier, secretlint, commitlint (Conventional Commits)
- [ ] `.github/workflows/ci.yml`: lint → typecheck → tests → build (matriz api/web/mobile), cache pnpm + uv
- [ ] `.github/workflows/security.yml`: `pip-audit`, `pnpm audit`, `trivy` em imagens Docker, `gitleaks` para secrets
- [ ] Coverage threshold: **85% service layer**, **70% total** (`pytest --cov --cov-fail-under=70`)
- [ ] Renovate/Dependabot com auto-merge em minor/patch
- [ ] Branch protection: PR obrigatório, CI verde, sem force-push em `main`
- [ ] `CONTRIBUTING.md` com padrões de branch/commit/PR
- [ ] `release-please` para changelog automático
- **Aceite:** PR de exemplo abre, CI roda todos os stages, coverage falha se abaixo do threshold, secret vazado é bloqueado no commit.

### Fase 1 — Auth JWT + 2FA · ~1.5 sessões (~4.5h)

- [ ] Model `User` + `RefreshToken` + Alembic init e 1ª migração (com `downgrade` testado)
- [ ] `POST /auth/register`, `POST /auth/login` (OAuth2PasswordRequestForm), `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`
- [ ] **Argon2id** via passlib; política: min 12 chars, checagem contra HIBP k-anonymity opt-in
- [ ] Access 15min + refresh 30d com **rotation + reuse detection** (jti revogado no Redis dispara logout global)
- [ ] **2FA/TOTP**: `POST /auth/2fa/setup` (QR + backup codes), `POST /auth/2fa/verify`, `POST /auth/2fa/disable`
- [ ] `get_current_user` dependency que injeta `SET LOCAL app.current_user_id` para RLS
- [ ] **TDD**: registro, login ok, senha errada 401, token inválido 401, refresh rotation, reuse de refresh revogado dispara logout, 2FA obrigatório após ativação, backup code consome-se
- **Aceite:** Swagger mostra lock; teste de segurança "usuário B usa token de A → 401"; refresh reusado invalida sessão.

### Fase 1.5 — Segurança de Base · ~1 sessão (3h) — **NOVA**

- [ ] **Rate limit** (SlowAPI + Redis): 5/min em `/auth/login`, 3/min em `/auth/register`, 100/min global por IP
- [ ] **Account lockout**: 5 falhas → 15min bloqueio, com backoff exponencial; log em `audit_events`
- [ ] **Audit log** para: login, logout, senha alterada, 2FA on/off, delete de conta, edição retroativa (>7d) de transação
- [ ] **RLS** habilitada em todas as tabelas com `user_id`; teste "SELECT sem user_id no session → 0 rows"
- [ ] **Headers de segurança** no Next.js: CSP, HSTS, X-Frame-Options DENY, Referrer-Policy same-origin
- [ ] **CORS** whitelist explícita (env `CORS_ORIGINS`); nada de `*`
- [ ] **Secret management**: `.env.example` documentado; produção usa Docker secrets ou env do orquestrador
- [ ] **Sanitização input/output**: Pydantic `In`/`Out` separados (proteção contra mass assignment)
- **Aceite:** ZAP baseline scan sem findings High; teste "usuário B consulta recurso A → 404 (não 403, para não vazar existência)"; rate limit bloqueia após N tentativas.

### Fase 2 — Contas, categorias e lançamentos (núcleo contábil) · ~2 sessões (~6h)

- [ ] Models `Account`, `Category`, `Tag`, `Transaction`, `AuditEvent`, `ImportBatch`, `AccountBalanceSnapshot` + migrações reversíveis
- [ ] Importação idempotente: SHA-256 do arquivo, `external_id` quando disponível, fingerprint determinístico como fallback e fila "A classificar"
- [ ] Reconciliação de saldo calculado contra `account_balance_snapshots` importado do extrato
- [ ] CRUD contas (com `archived`, `currency`), CRUD categorias (com hierarquia opcional), CRUD tags
- [ ] Criar lançamento income/expense (com anexo opcional), listar com paginação + filtros (mês, conta, categoria, tag, texto)
- [ ] Edição via **transação reversora + nova** (append-only), soft-delete via `status=canceled`, com audit
- [ ] `GET /accounts/{id}/balance` (saldo posted) + `GET /accounts/{id}/balance/projected?date=` (com pending)
- [ ] Service de saldo isolado (puro, testável) — **proibido** calcular saldo em router
- [ ] **Property-based tests com hypothesis**: invariante "saldo == sum(tx) + initial" para milhares de sequências
- [ ] TDD casos: saldo inicial, income/expense somam, transferência atômica cria par, estorno restaura saldo exato, edição concorrente devolve 409
- **Aceite:** cenário: conta A com saldo inicial 1000 → +500 salário → −120 mercado → transferência de 200 para conta B criada sem saldo inicial ⇒ **saldo final A = 1180** (1000 + 500 − 120 − 200) e **saldo final B = 200** (0 + 200); transferência cria 2 transações atômicas unidas por `transfer_group_id`; hypothesis roda 500 exemplos sem quebrar invariante (`saldo == initial + Σ tx posted`); reconciliação SQL bruta bate.
- [ ] Web: telas de contas + lista de lançamentos + formulário (react-hook-form + zod via shared-types) + upload de anexo

### Fase 3 — Transferências, agendados, recorrências e dashboard · ~1.5 sessões (~4.5h)

- [ ] Endpoint de transferência (única DB transaction criando o par)
- [ ] **Agendados**: criar transaction com `status=pending` e `date` futura; job diário promove a `posted` no dia
- [ ] **Recorrências**: CRUD de `recurring_transactions`; job diário materializa lançamentos com `next_run_on <= today`
- [ ] Dashboard: saldo total consolidado (por moeda), por conta, fluxo do mês, próximos agendados, últimos lançamentos
- [ ] Gráfico de evolução (recharts) e comparativo mês a mês
- **Aceite:** transferência reflete nos 2 saldos; recorrência mensal dia 5 gera lançamento em três meses simulados; agendado do dia 30 vira posted quando o job roda com data > 30.

### Fase 4 — Cartões de crédito, faturas e parcelamento · ~2.5 sessões (~7.5h)

O ponto mais delicado do domínio. TDD antes da UI.

- [ ] Model `CreditCard` + `CardInvoice` (materializada) + `InvoicePayment` (append-only); job idempotente de fechamento
- [ ] Encargos tipados: juros, multa, IOF, tarifa de saque e outros
- [ ] Compra no cartão: à vista OU parcelada em N (cria N transações em faturas consecutivas)
- [ ] Pagamento de fatura (total/parcial); status da fatura evolui automaticamente
- [ ] Limite disponível = `limit_cents` − Σ(compras em faturas open/closed não pagas − parcelas futuras já contadas)
- [ ] Fatura como "conta virtual" na UI: lista de faturas por cartão, compras da fatura aberta e das próximas (parcelas futuras)
- [ ] **TDD casos-monstro**:
  - Compra dia 30 com fechamento dia 25 → fatura do mês seguinte
  - Compra dia 24 com fechamento dia 25 → fatura corrente
  - Parcelada 3x em fev/29 → parcelas em mar/29, abr/29, mai/29
  - Pagamento parcial baixa `paid_cents` e mantém status `partially_paid`
  - Rerun do job de fechamento **não duplica** fatura
  - Estorno de compra parcelada remove todas as N parcelas
- [ ] Web + mobile: tela do cartão, fatura aberta, próximas faturas (com parcelas futuras), pagar fatura
- **Aceite:** simulação de 3 compras (2 à vista + 1 parcelada 3x) em meses diferentes, fechamento, pagamento parcial → saldo da conta, exposição do cartão e status das faturas conferem com planilha manual documentada no teste.

### Fase 5 — Orçamentos, alertas e recorrências de orçamento · ~1 sessão (3h)

- [ ] CRUD de orçamento por categoria/mês (com "repetir todo mês" — cria em lote; com `rollover` opcional)
- [ ] Progresso do orçamento (gasto vs limite), alertas 80%/100% no backend e badges na UI
- [ ] `GET /budgets/summary?month=` — visão consolidada
- [ ] TDD: mês sem gastos, 80% → warning, estourado, categoria sem orçamento, rollover soma sobra
- **Aceite:** orçamento 500 alimentação, lançar 410 → badge "atenção"; +100 → "estourado"; próximo mês com rollover ativo **herda apenas a sobra positiva do mês anterior** (ex.: sobraram 90 de 500 com 410 gastos → limite do próximo mês vira 590); **déficit não é transportado** (gasto 600 de 500 → próximo mês começa em 500, sem herdar −100; revisão manual cabe ao usuário).

### Fase 6 — App Android (Expo) com offline-first · ~2.5 sessões (~7.5h)

- [ ] `apps/mobile`: Expo Router, telas de login (com 2FA), contas, lançamentos, novo lançamento, cartões, fatura, orçamentos, agendados, recorrências
- [ ] **Offline-first**: `expo-sqlite` como cache local; TanStack Query com `persistQueryClient`; fila de mutations com retry idempotente (Idempotency-Key header)
- [ ] Optimistic UI com rollback em erro
- [ ] Reconciliação de sync com resolução de conflito por `version` (server-wins com aviso)
- [ ] SecureStore p/ tokens, refresh automático no 401, biometria (`expo-local-authentication`) para desbloqueio
- [ ] Certificate pinning (react-native-ssl-pinning) em produção
- [ ] Deep linking (`finance://transaction/:id`)
- [ ] Splash, ícone adaptativo Android, assets otimizados
- [ ] Build de desenvolvimento com EAS (`--profile development --platform android`); Expo Go para dev diário
- [ ] **E2E Maestro**: fluxo login → criar conta → lançamento → ver saldo → simular offline → sync
- **Aceite:** fluxo completo online e **offline** (avião ligado): criar 3 lançamentos, sincroniza ao voltar; biometria desbloqueia sessão; teste E2E Maestro verde.

### Fase 6.5 — Observabilidade · ~1 sessão (3h) — **NOVA**

- [ ] **Logging estruturado** (structlog JSON) com correlation ID por request (middleware) — API, web SSR e mobile
- [ ] **Sentry** integrado (API, web, mobile) com `send_default_pii=false`; source maps para web e mobile
- [ ] **Prometheus** `/metrics` via `prometheus-fastapi-instrumentator`; métricas customizadas: transactions/min, saldo recomputes, refresh reuse detected
- [ ] Log de queries lentas Postgres (`log_min_duration_statement=500ms`)
- [ ] Uptime externo (UptimeRobot ou similar) em `/health/ready` e página inicial da web
- [ ] Alertas básicos (Sentry rules): erro > 5% em 5min, latência p95 > 2s
- **Aceite:** um erro forçado aparece no Sentry com correlation ID igual em API/web; `/metrics` retorna série temporal; log de request tem timing + user_id + trace.

### Fase 7 — Empacotamento produção · ~1 sessão (3h)

- [ ] Dockerfiles multi-stage otimizados (api: builder + runtime slim; web: standalone Next)
- [ ] `docker-compose.prod.yml` com healthchecks, restart policies, secrets
- [ ] Migrations rodam idempotentes no start da api (com lock)
- [ ] Backups automáticos: `pg_dump` diário via cron container → S3-compat; **restore testado semanalmente** (job compara checksum)
- [ ] Rotate JWT secret com grace period documentado
- **Aceite:** `docker compose -f docker-compose.prod.yml up` sobe tudo com healthcheck verde; backup gerado e **restaurado em ambiente limpo** valida integridade.

### Fase 7.5 — LGPD e conformidade · ~1 sessão (3h) — **NOVA**

- [ ] `docs/privacy/policy-pt-br.md` (política de privacidade), `terms-pt-br.md` (termos de uso), `lgpd-map.md` (bases legais por tratamento)
- [ ] `GET /users/me/export` — export completo em JSON + ZIP com anexos (**direito à portabilidade**)
- [ ] `DELETE /users/me` — apaga de fato (não flag): transactions, accounts, cards, invoices, budgets, tokens, attachments no storage; audit fica anonimizado por 6 meses (obrigação legal) e depois é apagado
- [ ] Consent explícito para Sentry/telemetria com toggle em `Configurações`
- [ ] Data retention documentada (audit logs: 12 meses; refresh tokens revogados: 30d; anexos: enquanto ativa a conta)
- [ ] Header `X-Robots-Tag: noindex` em rotas autenticadas
- **Aceite:** delete de usuário deixa 0 rows relacionadas em query de auditoria; export baixa ZIP válido com todos os dados do usuário.

### Fase 8 — Deploy + operação · ~1 sessão (3h)

- [ ] Deploy backend (VPS Docker que o usuário domina) + Postgres com backup off-site
- [ ] Web deploy: **decisão pendente Vercel vs VPS** — decidir antes desta fase (ver riscos)
- [ ] Android: `eas build --profile production` + `.aab` interno (sem Play Store no MVP)
- [ ] DNS, TLS (Let's Encrypt via Caddy/Traefik), CDN opcional
- [ ] Runbook: `docs/runbook/restore-db.md`, `rotate-secrets.md`, `incident-response.md`
- **Aceite:** app Android instalado no dispositivo do usuário conversando com API em produção; web acessível publicamente; runbook testado (restore executado seguindo o passo-a-passo).

### Fase 9 — Pós-MVP (backlog priorizado)

- Import OFX/CSV manual com deduplicação
- Metas de reserva e objetivos (envelope method)
- Relatórios avançados (evolução por categoria, sankey de fluxo)
- Notificações push (Expo Notifications) para alertas de orçamento e vencimento de fatura
- Contas compartilhadas / famílias
- PWA offline para a web
- Multi-moeda com câmbio (API do BCB)
- Integração Open Finance (Belvo/Pluggy) quando fizer sentido

---

## Files likely to change (Fases 0-1.5, execução imediata)

- Create: `package.json`, `pnpm-workspace.yaml`, `turbo.json`, `docker-compose.yml`, `.pre-commit-config.yaml`, `README.md`, `.gitignore`, `.env.example`
- Create: `.github/workflows/ci.yml`, `security.yml`
- Create: `apps/api/app/main.py`, `core/config.py`, `core/security.py`, `core/ratelimit.py`, `core/telemetry.py`, `db/session.py`, `db/rls.py`, `models/user.py`, `models/refresh_token.py`, `models/audit_event.py`, `routers/auth.py`, `services/auth_service.py`
- Create: `apps/api/alembic/` + 1ª migração
- Create: `docs/architecture/c4-context.md`, `CONTRIBUTING.md` (ADRs 0001–0004 já existem em `docs/decisions/accepted/` — apenas commitados)
- Test: `apps/api/tests/unit/test_security.py`, `integration/test_auth.py`, `security/test_rls_isolation.py`, `security/test_rate_limit.py`

## Tests / validation (padrão por fase)

- **Backend unit** (`apps/api/tests/unit/`): services puros, sempre com **hypothesis** quando houver invariante numérica. Coverage ≥ 85%.
- **Backend integration** (`apps/api/tests/integration/`): routers via `httpx.AsyncClient` contra app de teste com DB de teste (transação com rollback por teste).
- **Backend security** (`apps/api/tests/security/`): scope isolation, RLS, replay de refresh, brute force, mass assignment.
- **Backend property** (`apps/api/tests/property/`): invariantes contábeis (`saldo == initial + sum(tx)`, `Σ(fatura) == Σ(compras da fatura)`).
- **Web unit**: `pnpm --filter web test` (Vitest) para lógica de formulários e domain-rules compartilhado.
- **Web E2E**: Playwright cobrindo login → criar conta → lançamento → ver saldo → criar orçamento.
- **Mobile E2E**: Maestro cobrindo o fluxo crítico + cenário offline.
- **Contract tests**: schema OpenAPI gerado pela API é comparado ao esperado por `api-client` em CI (falha se drift).
- **Security scan**: ZAP baseline no CI de PR contra ambiente efêmero.
- **Load test**: k6 script em `apps/api/tests/load/` — smoke rodado no CI, load rodado on-demand.

## Estimativas e cadência

- **Unidade "sessão" = 3h focadas.** Total MVP (Fases 0 → 8) ≈ **~20 sessões ≈ ~60h**.
- **Buffer de 25%** já embutido nas estimativas. Se um card estoura +50%, quebrar em subcards.
- **Grafo de dependências** (não linear estrito):
  - `0 → 0.5 → 1 → 1.5 → 2` (obrigatório sequencial)
  - `2 → {3, 4}` (paralelizável)
  - `{3, 4, 5} → 6 → 6.5 → 7 → 7.5 → 8`
- Cada fase abre com **plano da fase** (subagent `subagent-driven-development`) e fecha com **retro curta** (o que quebrou, o que ficou).

## Documentação (viva, versionada)

- **ADRs** (Nygard): decisões arquiteturais com contexto/decisão/consequência, em `docs/decisions/` (registry `scripts/decisions.py`); 0001–0004 já aceitos na Pre-0.
- **C4 Model**: context, container, component em `docs/architecture/` (draw.io ou d2 versionado).
- **OpenAPI**: `docs/api/openapi.yaml` versionado; gerado pelo FastAPI e commitado; drift falha CI.
- **Runbook** operacional (fase 8): restore-db, rotate-secrets, deploy, incident-response.
- **Changelog** automático via `release-please` a cada tag semver.
- **CONTRIBUTING.md**: padrões de commit (Conventional Commits), branch (`feat/`, `fix/`, `chore/`), PR (template).

## Risks / tradeoffs / open questions

| Risco | Impacto × Probabilidade | Mitigação / gatilho |
|---|---|---|
| **Complexidade de faturas + parcelamento** (compra dia 30 com fechamento 25 vai para fatura seguinte; parcelas em faturas futuras) | Alto × Alta | TDD casos-monstro **antes** da UI (Fase 4); planilha manual documentada como oracle. |
| **Vazamento entre usuários** por bug de scope | Alto × Média | RLS no Postgres + teste dedicado "usuário B lê recurso A → 404" em toda entidade. |
| **Perda ou corrupção do ledger** | Crítico × Baixa | Append-only + backup diário + **restore automatizado testado semanalmente** + property tests de reconciliação. |
| **Deriva de saldo por race em edit concorrente** | Médio × Média | Optimistic locking via `version` + 409; hypothesis stress test em sequências paralelas. |
| **Append-only gera tabelas grandes** | Baixo × Baixa | Volume pessoal: irrelevante no MVP; particionamento por ano previsto no pós-MVP se >1M rows. |
| **Lock-in em Expo/EAS** | Médio × Média | Planejar bare workflow como saída documentada; evitar módulos que só funcionam com managed. |
| **Custo de manutenção do RN** (breaking em upgrades) | Médio × Alta | Política: upgrade N-1 sempre; smoke E2E Maestro roda em CI para pegar regressão. |
| **Refresh token roubado do SecureStore** | Alto × Baixa | Rotation + reuse detection + biometria + certificate pinning. |
| **Vercel free tier limita SSR autenticado** | Baixo × Média | Fallback documentado para VPS com Docker (mesma imagem). |
| **LGPD infringida por telemetria vazando PII** | Alto × Baixa | `send_default_pii=false` + consent explícito + auditoria periódica dos eventos Sentry. |

**Tradeoffs aceitos:**
- Refresh token em SecureStore (mobile) em vez de httpOnly cookie — padrão Expo, aceitável com rotation + reuse detection + biometria.
- Sem particionamento no MVP (YAGNI para volume pessoal).
- Sem multi-moeda funcional no MVP, mas **campo `currency` existe** desde o dia 1 (migração cara evitada).
- Sem push notifications no MVP — alertas ficam em badge/email.

**Fechado/adiado:**
1. **Deploy web:** VPS (fechado na Pre-0).
2. **Nome do app:** Cifra; package provisório `br.com.usarcifra.app`, confirmar antes da Fase 6.
3. **Storage de anexos em produção:** Cloudflare R2; MinIO apenas no desenvolvimento.
4. **Sentry:** plano free com sampling agressivo e sem PII.
5. **Email:** Resend; somente compra/configuração do domínio `usarcifra.com.br` permanece adiada até antes da Fase 1.5.

---

## Definition of Done (transversal)

Uma fase só fecha quando:
1. Todos os checkboxes marcados.
2. Critérios de aceite verificados por teste automatizado (não visual).
3. CI verde (lint + typecheck + tests + security).
4. Coverage ≥ threshold.
5. Migrations testadas em `up` **e** `down`.
6. Documentação atualizada (ADR se houve decisão, README se comando mudou, OpenAPI se rota mudou).
7. Nenhum `TODO`/`FIXME` novo sem issue vinculada.
8. Retro curta commitada em `docs/decisions.md`.
