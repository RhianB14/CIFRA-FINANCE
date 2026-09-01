# FINANCE PROJ — Roadmap (planilha em Markdown)

> Conversao fiel da planilha `finance-proj-roadmap.xlsx` (2026-08-29). Cores e freeze-panes nao sao representaveis em Markdown; o conteudo textual esta preservado integralmente em 6 secoes espelhando as abas.

## Sumario

1. [Resumo](#1-resumo)
2. [Roadmap](#2-roadmap)
3. [Cronograma](#3-cronograma)
4. [Entregaveis](#4-entregaveis)
5. [Riscos](#5-riscos)
6. [Decisoes pendentes](#6-decisoes-pendentes)

---

## 1. Resumo

**FINANCE PROJ — Roadmap Executivo**

_Gerado em 2026-08-29 (Sabado) — America/Sao_Paulo_

### Indicadores

| Indicador | Valor |
|---|---|
| Total de fases (MVP) | 14 |
| Total de sessoes estimadas | 19 |
| Total de horas estimadas | 57 |
| Buffer embutido | 25% |
| Cadencia assumida | 2 sessoes/semana (6h/sem) |
| Duracao sessao | 3h focadas |
| Data de inicio | 2026-09-01 |
| Data prevista de MVP | 2026-11-10 |
| Semanas ate MVP | 10 |

### Legenda por tipo de fase

| Tipo | Descricao |
|---|---|
| Preparacao | Antes do git init — decisoes, validacao de dominio, ADRs |
| Infra | Docker, monorepo, CI/CD, empacotamento e deploy |
| Backend | FastAPI, models, services, migracoes |
| Seguranca | Auth, 2FA, rate limit, RLS, audit, LGPD tecnica |
| Dominio | Regras contabeis: saldo, faturas, orcamentos, recorrencia |
| Mobile | Expo, offline-first, biometria |
| Ops | Observabilidade, backup, runbook, alertas |
| Compliance | LGPD, politica de privacidade, termos, retencao |
| Backlog | Pos-MVP — sem prazo fixo |

---

## 2. Roadmap

Linha por fase com objetivo, criterio de aceite e prazos estimados. Total no final agrega sessoes e horas do MVP (excluindo F9 Backlog).

| ID | Fase | Tipo | Sessoes | Horas | Inicio | Fim previsto | Objetivo | Criterio de aceite | Status |
|---|---|---|---|---|---|---|---|---|---|
| Pre-0 | Preparacao (decisoes + validacao dominio) | Preparacao | 1 | 3 | 2026-09-01 | 2026-09-04 | Fechar decisoes + validar schema com extratos reais + ADRs 0001-0004 + preparar ambiente local | 7/8 decisoes fechadas (somente dominio adiado); Resend criado; dataset real reconciliado; gaps G1-G5 incorporados; ADRs aceitos; ambiente completo verificado, incluindo Android Studio/JDK/SDK/ADB e boot real do AVD Android 16 | Concluida |
| F0 | Fundacao (monorepo + infra base) | Infra | 1 | 3 | 2026-09-05 | 2026-09-08 | Init do monorepo, docker-compose de dev e esqueleto funcional de api+web+mobile; versionar ADRs 0001-0004 ja aceitos | Aceite verificado em 29/08: Compose com 5 servicos saudaveis; live/ready 200; ready 503 com Redis parado; web responde Cifra/API operacional; API 3 testes; lint/typecheck/build/Expo validos; imports e .env ignorados | Concluida |
| F0.5 | CI/CD e qualidade | Infra | 1 | 3 | 2026-09-09 | 2026-09-12 | Pipelines GitHub Actions, pre-commit, coverage threshold, security scans, branch protection | Correcao rigorosa 30/08/26: gate unificado renomeado para `pnpm verify` (`pnpm ci` colidia com comando interno do pnpm); python substituido por `uv run`/uvx em todos os scripts e pre-commit; checker de comentarios cobre ignorefiles, .env.example, TOML e INI, com erro explicito para formato desconhecido; gitleaks e o gate local primario (staged) com allowlist provada por segredo falso nos 3 caminhos; check-merge-conflict adicionado; imagem web limpa de CVEs HIGH/CRITICAL (pnpm standalone, npm removido) e `.trivyignore-web` excluido; permissao `security-events: write` removida do workflow Security; excecoes MinIO documentadas em docs/security-exceptions.md | Concluida localmente (pendencias remotas: push, workflows no GitHub, branch protection, auto-merge, release-please) |
| F1 | Auth JWT + 2FA | Backend | 1.5 | 4.5 | 2026-08-30 | 2026-08-31 | Registro, login, refresh rotation com reuse detection, 2FA/TOTP, argon2id | 176 testes verdes contra PostgreSQL/Redis reais; ADR 0005 aceita; OpenAPI deterministico em docs/api/openapi.yaml com drift check; smoke test de auth no CI; Swagger com lock; refresh reusado invalida sessao; 2FA obrigatorio quando ativado; teste scope-isolation verde | Concluida (PR #12 mergeado via squash como aee2091 em 2026-09-01; incorporada a main) |
| F1.5 | Seguranca de base | Seguranca | 1 | 3 | 2026-09-18 | 2026-09-21 | Rate limit, account lockout, audit log, RLS Postgres, headers CSP/HSTS, CORS whitelist | ZAP baseline sem findings High; teste 'usuario B le recurso A -> 404'; rate limit bloqueia apos N tentativas | Em revisao (PR aberto; implementacao concluida em feat/f1.5-security) |
| F2 | Contas e lancamentos (nucleo contabil) | Dominio | 2 | 6 | 2026-09-22 | 2026-09-28 | CRUD contas/categorias/tags, transactions append-only, importacao manual CSV idempotente, reconciliacao por snapshots, service de saldo puro, property-based tests | Conta A: 1000 + 500 - 120 - 200 = 1180; conta B com saldo inicial 0 recebe 200 e termina em 200; Hypothesis roda 500 exemplos; reimportar CSV nao duplica; reconciliacao SQL e snapshot batem | Pendente |
| F3 | Transferencias, agendados, recorrencias, dashboard | Dominio | 1.5 | 4.5 | 2026-09-29 | 2026-10-03 | Transferencia atomica, jobs de agendados e recorrencias, dashboard web com saldo consolidado + fluxo do mes | Transferencia reflete nos 2 saldos; recorrencia mensal gera lancamento em 3 meses simulados; agendado vira posted no job | Pendente |
| F4 | Cartoes, faturas e parcelamento | Dominio | 2.5 | 7.5 | 2026-10-04 | 2026-10-12 | CreditCard + CardInvoice materializada, parcelamento N x, pagamento parcial, casos-monstro TDD | Simulacao 3 compras (2 a vista + 1 parcelada 3x), fechamento, pagamento parcial -> saldos e exposicao conferem com planilha manual | Pendente |
| F5 | Orcamentos, alertas e rollover | Dominio | 1 | 3 | 2026-10-13 | 2026-10-16 | CRUD budget, progresso, alertas 80%/100%, rollover opcional apenas de saldo positivo disponivel | Orcamento 500, gasto 410 -> warning e rollover seguinte 90; gasto total 510 -> over_budget e nenhum deficit transportado automaticamente | Pendente |
| F6 | App Android com offline-first | Mobile | 2.5 | 7.5 | 2026-10-17 | 2026-10-25 | Expo Router, SQLite local, TanStack Query persist, fila de mutations idempotentes, biometria, cert pinning | Fluxo completo online e offline (avião ligado); biometria desbloqueia; teste E2E Maestro verde | Pendente |
| F6.5 | Observabilidade | Ops | 1 | 3 | 2026-10-26 | 2026-10-29 | structlog JSON + correlation ID, Sentry, Prometheus /metrics, uptime externo, alertas | Erro forcado aparece no Sentry com correlation ID igual em API/web; /metrics retorna serie temporal | Pendente |
| F7 | Empacotamento producao | Infra | 1 | 3 | 2026-10-30 | 2026-11-02 | Dockerfiles multi-stage, compose prod, migracoes idempotentes, backup pg_dump com restore testado | docker compose prod sobe com healthcheck verde; backup restaurado em ambiente limpo valida integridade | Pendente |
| F7.5 | LGPD e conformidade | Compliance | 1 | 3 | 2026-11-03 | 2026-11-06 | Politica, termos, mapa LGPD, export completo do usuario, delete real (nao flag), consent de telemetria | Delete de usuario deixa 0 rows relacionadas; export baixa ZIP valido com todos os dados; policy publicada | Pendente |
| F8 | Deploy e operacao | Infra | 1 | 3 | 2026-11-07 | 2026-11-10 | Deploy backend VPS + Postgres com backup off-site, web deploy, Android EAS production build, runbook | App Android instalado no dispositivo conversando com API prod; web publica; runbook testado com restore real | Pendente |
| F9 | Pos-MVP (backlog priorizado) | Backlog | 0 | 0 | - | - | Import OFX, integracoes bancarias automaticas/Open Finance, metas de reserva, relatorios avancados, push notifications, contas compartilhadas, PWA e multi-moeda; CSV manual idempotente ja pertence a F2 | Sem prazo fixo — priorizar por uso real apos MVP em producao | Backlog |
|  |  | TOTAL MVP | 19 | 57 |  |  |  |  |  |

---

## 3. Cronograma (Gantt textual)

`X` marca as semanas em que a fase esta ativa. S1 = semana comecando em 2026-09-01.

| Fase | Tipo | S1 01/09 | S2 08/09 | S3 15/09 | S4 22/09 | S5 29/09 | S6 06/10 | S7 13/10 | S8 20/10 | S9 27/10 | S10 03/11 | S11 10/11 | S12 17/11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pre-0 Preparacao (decisoes + validacao dominio) | Preparacao | X |  |  |  |  |  |  |  |  |  |  |  |
| F0 Fundacao (monorepo + infra base) | Infra | X | X |  |  |  |  |  |  |  |  |  |  |
| F0.5 CI/CD e qualidade | Infra |  | X |  |  |  |  |  |  |  |  |  |  |
| F1 Auth JWT + 2FA | Backend |  | X | X |  |  |  |  |  |  |  |  |  |
| F1.5 Seguranca de base | Seguranca |  |  | X |  |  |  |  |  |  |  |  |  |
| F2 Contas e lancamentos (nucleo contabil) | Dominio |  |  |  | X |  |  |  |  |  |  |  |  |
| F3 Transferencias, agendados, recorrencias, dashboard | Dominio |  |  |  |  | X |  |  |  |  |  |  |  |
| F4 Cartoes, faturas e parcelamento | Dominio |  |  |  |  | X | X |  |  |  |  |  |  |
| F5 Orcamentos, alertas e rollover | Dominio |  |  |  |  |  |  | X |  |  |  |  |  |
| F6 App Android com offline-first | Mobile |  |  |  |  |  |  | X | X |  |  |  |  |
| F6.5 Observabilidade | Ops |  |  |  |  |  |  |  | X | X |  |  |  |
| F7 Empacotamento producao | Infra |  |  |  |  |  |  |  |  | X |  |  |  |
| F7.5 LGPD e conformidade | Compliance |  |  |  |  |  |  |  |  |  | X |  |  |
| F8 Deploy e operacao | Infra |  |  |  |  |  |  |  |  |  | X | X |  |

---

## 4. Entregaveis

Lista granular de artefatos por fase. Prioridade: **Critica** (bloqueante), **Alta**, **Media**, **Baixa**.

### Pre-0

| Entregavel | Tipo | Prioridade |
|---|---|---|
| 5 decisoes escritas (nome, Vercel vs VPS, storage, email, Sentry) | Documento | Critica |
| docs/domain-validation.csv com 30+ lancamentos reais mapeados no schema | Documento | Critica |
| ADRs 001-004 (append-only, currency per account, optimistic locking, RLS) | Documento | Alta |
| Ambiente local: Docker, Python 3.11+uv, Node 20+pnpm, Expo, Android emulator | Infra local | Critica |

### F0

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Monorepo pnpm + turbo + apps/api + apps/web + apps/mobile mínimo (Expo Router + TS) + packages/{shared-types,api-client,domain-rules} | Codigo | Critica |
| docker-compose.yml dev (postgres, redis, minio, api, web) | Infra | Critica |
| README.md, .gitignore, .env.example | Documento | Alta |
| ADRs 0001-0004 aceitos na Pre-0, em docs/decisions/accepted/, versionados sem duplicacao | Documento | Alta |
| docs/architecture/c4-context.md esboco | Documento | Media |

### F0.5

| Entregavel | Tipo | Prioridade |
|---|---|---|
| .pre-commit-config.yaml (ruff, mypy strict, eslint, prettier, secretlint, commitlint) | Qualidade | Alta |
| .github/workflows/ci.yml (lint, typecheck, tests, build) | CI/CD | Alta |
| .github/workflows/security.yml (pip-audit, pnpm audit, trivy, gitleaks) | CI/CD | Alta |
| Coverage threshold configurado (85% service / 70% total) | Qualidade | Alta |
| Dependabot configurado (pnpm, pip, actions, docker) + branch protection main | CI/CD | Media |
| CONTRIBUTING.md + release-please | Documento | Media |

### F1

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Model User + RefreshToken + AuditEvent + 1a migracao Alembic reversivel | Backend | Critica |
| Rotas /auth/{register,login,refresh,logout,me} | Backend | Critica |
| Argon2id + politica de senha + HIBP opcional | Seguranca | Alta |
| Refresh rotation + reuse detection via Redis (jti revogado) | Seguranca | Critica |
| 2FA/TOTP com backup codes | Seguranca | Alta |
| get_current_user injeta SET LOCAL app.current_user_id (RLS) | Backend | Critica |
| Testes: registro, login, 401 casos, rotation, reuse, 2FA obrigatorio | Teste | Alta |

### F1.5

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Rate limit SlowAPI + Redis (5/min login, 3/min register, 100/min global) | Seguranca | Critica |
| Account lockout 5 falhas + backoff exponencial | Seguranca | Alta |
| Tabela audit_events + service de log estruturado | Seguranca | Alta |
| RLS policies em todas as tabelas com user_id | Seguranca | Critica |
| Headers CSP/HSTS/X-Frame-Options no Next.js | Seguranca | Alta |
| CORS whitelist via env | Seguranca | Alta |
| Schemas In/Out separados (anti mass assignment) | Seguranca | Media |
| Teste ZAP baseline + scope isolation | Teste | Alta |

### F2

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Models Account, Category, Tag, Transaction, ImportBatch, AccountBalanceSnapshot + migracoes | Backend | Critica |
| Importacao idempotente por SHA-256/external_id/fingerprint + fila A classificar | Backend | Critica |
| Reconciliacao contra snapshots de saldo bancario | Backend | Critica |
| CRUD contas/categorias/tags | Backend | Alta |
| Service de saldo puro (isolado, testavel) | Backend | Critica |
| GET /accounts/{id}/balance e balance/projected | Backend | Alta |
| Property-based tests (hypothesis) do saldo | Teste | Critica |
| Edicao via reversora + version 409 concorrencia | Backend | Alta |
| Upload de anexo (MinIO) | Backend | Media |
| Web: telas contas + lista + form de lancamento (RHF + zod) | Web | Alta |

### F3

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Endpoint de transferencia atomica (par transaction) | Backend | Critica |
| Job diario de agendados (pending -> posted) | Backend | Alta |
| CRUD recurring_transactions + job materializador | Backend | Alta |
| Dashboard web: saldo consolidado, por conta, fluxo do mes | Web | Alta |
| Grafico de evolucao mensal (recharts) | Web | Media |

### F4

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Model CreditCard + CardInvoice + InvoicePayment append-only + job de fechamento idempotente | Backend | Critica |
| Encargos tipados (juros, multa, IOF, tarifa de saque, outros) | Backend | Alta |
| Compra a vista + parcelada (N x, installment_group_id) | Backend | Critica |
| Pagamento total/parcial de fatura | Backend | Alta |
| Endpoint limite disponivel | Backend | Alta |
| TDD casos-monstro (compra entre fechamentos, rerun idempotente, estorno) | Teste | Critica |
| Web + mobile: tela cartao, fatura aberta, proximas faturas, pagar | Web+Mobile | Alta |

### F5

| Entregavel | Tipo | Prioridade |
|---|---|---|
| CRUD budget + repetir todo mes + rollover | Backend | Alta |
| Endpoint progresso e alertas 80%/100% | Backend | Alta |
| Badges e cards de orcamento na UI | Web | Media |

### F6

| Entregavel | Tipo | Prioridade |
|---|---|---|
| apps/mobile Expo Router + telas espelhando web | Mobile | Critica |
| Offline-first: expo-sqlite + TanStack persist + fila de mutations | Mobile | Critica |
| SecureStore + refresh automatico + biometria (expo-local-authentication) | Seguranca | Alta |
| Certificate pinning em producao | Seguranca | Media |
| Deep linking + splash + icone adaptativo | Mobile | Media |
| EAS build development + Expo Go | Mobile | Alta |
| E2E Maestro fluxo critico + cenario offline | Teste | Alta |

### F6.5

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Logging structlog JSON com correlation ID (middleware) | Ops | Alta |
| Sentry integrado (api, web, mobile) sem PII | Ops | Alta |
| Prometheus /metrics + metricas customizadas | Ops | Media |
| Uptime externo + alertas basicos | Ops | Alta |

### F7

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Dockerfiles multi-stage prod (api + web) | Infra | Critica |
| docker-compose.prod.yml com healthchecks e secrets | Infra | Critica |
| Migracoes idempotentes no start com lock | Backend | Alta |
| Backup pg_dump diario -> S3-compat | Ops | Critica |
| Job semanal de restore-test com checksum | Ops | Alta |

### F7.5

| Entregavel | Tipo | Prioridade |
|---|---|---|
| docs/privacy/{policy-pt-br,terms-pt-br,lgpd-map}.md | Compliance | Critica |
| GET /users/me/export (JSON + ZIP com anexos) | Backend | Alta |
| DELETE /users/me com apagamento real | Backend | Critica |
| Consent explicito para Sentry + toggle em Configuracoes | Compliance | Alta |
| Data retention documentada | Documento | Media |

### F8

| Entregavel | Tipo | Prioridade |
|---|---|---|
| Deploy backend VPS + Postgres + backup off-site | Deploy | Critica |
| Deploy web (VPS ou Vercel — decidido em Pre-0) | Deploy | Critica |
| eas build --profile production + .aab interno | Deploy | Critica |
| DNS + TLS Let's Encrypt (Caddy/Traefik) | Infra | Alta |
| docs/runbook/{restore-db,rotate-secrets,incident-response}.md | Documento | Alta |
| App instalado no dispositivo do usuario + web publica | Deploy | Critica |

---

## 5. Riscos

Score = Impacto x Probabilidade (1-9). **>=7 vermelho, 4-6 amarelo, <4 verde** na planilha.

| Risco | Impacto | Probabilidade | Score | Mitigacao / gatilho |
|---|---|---|---|---|
| Complexidade de faturas + parcelamento (compra entre fechamentos, N parcelas em N faturas) | Alto | Alta | 9 | TDD casos-monstro ANTES da UI (F4); planilha manual documentada como oracle |
| Vazamento entre usuarios por bug de scope | Alto | Media | 6 | RLS Postgres + teste dedicado 'usuario B le recurso A -> 404' em cada entidade |
| Perda ou corrupcao do ledger | Critico | Baixa | 4 | Append-only + backup diario + restore automatizado testado semanalmente + property tests |
| Deriva de saldo por race em edit concorrente | Medio | Media | 4 | Optimistic locking via version + 409; hypothesis stress test em sequencias paralelas |
| Append-only gera tabelas grandes | Baixo | Baixa | 1 | Volume pessoal irrelevante no MVP; particionamento previsto pos-MVP se >1M rows |
| Lock-in Expo/EAS | Medio | Media | 4 | Planejar bare workflow como saida documentada; evitar modulos que so funcionam managed |
| Custo de manutencao RN (breaking em upgrades) | Medio | Alta | 6 | Politica: upgrade N-1 sempre; smoke E2E Maestro em CI para pegar regressao |
| Refresh token roubado do SecureStore | Alto | Baixa | 3 | Rotation + reuse detection + biometria + certificate pinning |
| Vercel free tier limita SSR autenticado | Baixo | Media | 2 | Fallback documentado para VPS Docker (mesma imagem) |
| LGPD infringida por telemetria vazando PII | Alto | Baixa | 3 | send_default_pii=false + consent explicito + auditoria periodica dos eventos Sentry |
| Cadencia real menor que 2 sessoes/semana | Medio | Alta | 6 | Buffer 25% embutido; se estourar 50%, quebrar cards e reduzir escopo do MVP |
| Decisoes em aberto travam fase (nome, Vercel, storage, email) | Alto | Alta | 9 | Fase Pre-0 dedicada a fechar antes de git init |

---

## 6. Status das decisoes da Pre-0

Fonte autoritativa: `docs/decisions.md`. **7 de 8 decisoes fechadas**. A unica pendencia deliberadamente adiada e a compra/configuracao do dominio de email.

| # | Decisao | Bloqueia fase | Recomendacao | Status | Prazo maximo |
|---|---|---|---|---|---|
| 1 | Nome do app + package Android | F6 | Cifra; usar provisoriamente `br.com.usarcifra.app` e confirmar antes da F6 | Fechada com identificador provisorio | Antes de F6 |
| 2 | Deploy web: Vercel ou VPS? | F7 | VPS (mesma infra da API, custo previsivel, sem tier limit) | Fechada: VPS | Concluida na Pre-0 |
| 3 | Storage de anexos em prod: MinIO / R2 / S3? | F7 | Cloudflare R2 (S3-compat, egress zero, 10GB free); MinIO so dev | Fechada: Cloudflare R2 | Concluida na Pre-0 |
| 4 | Provedor de email transacional | F1.5 | Resend (conta criada; remetente de teste ate ter dominio) | Fechada: Resend | Concluida na Pre-0 |
| 5 | Sentry: free ou pago? | F6.5 | Free com sampling agressivo e sem PII | Fechada: Free | Concluida na Pre-0 |
| 6 | Dominio do email (SPF/DKIM/DMARC) | F1.5 | Candidato `usarcifra.com.br`; compra/configuracao deliberadamente adiada | Adiada: unica pendencia | Antes de F1.5 |
| 7 | Licenca do repo (MIT vs UNLICENSED) | F0 | UNLICENSED enquanto privado | Fechada: UNLICENSED | Concluida na Pre-0 |
| 8 | Publicar no Play Store no MVP? | F8 | Nao; `.aab` interno via EAS | Fechada: nao publicar | Concluida na Pre-0 |

---

_Fim. Gerado a partir de finance-proj-roadmap.xlsx._
