# FINANCE PROJ — Decisões (Pre-0)

**Data:** 2026-08-29 · **Fase:** Pre-0 (preparação, pré git-init)
**Fontes:** `finance-proj-master-plan-v2.md` (arquitetura) · `finance-proj-roadmap.md` (cronograma e decisões pendentes)
**Estado do projeto em 2026-08-29:** Pre-0 concluído; decisões, validação de domínio, ADRs e ambiente local preparados. A implementação da aplicação começa na F0. Os planos v2 e roadmap permanecem como fonte da verdade de arquitetura e cronograma, complementados por esta decisão central e pelos ADRs aceitos.

---

## Status das decisões pendentes (roadmap §6)

| # | Decisão | Status | Resolução | Bloqueia |
|---|---|---|---|---|
| 1 | Nome do app | ✅ **FECHADA** | **Cifra** — escolhido pelo usuário | F6 (ícone/splash/package) |
| 2 | Deploy web | ✅ **FECHADA** | **VPS** — mesma infra Docker da API, custo previsível, sem tier limit | F7 |
| 3 | Storage de anexos (prod) | ✅ **FECHADA** | **Cloudflare R2** — S3-compat, egress zero, 10 GB free; MinIO permanece só no dev (compose) | F7 |
| 4 | Email transacional | ✅ **FECHADA** | **Resend** — DX melhor, 3k/mês free | F1.5 |
| 5 | Sentry free ou pago | ✅ **FECHADA** | **Free** — sampling agressivo desde o dia 1 (`send_default_pii=false`) | F6.5 |
| 6 | Domínio do email | 🟡 **ADIADO** | Usuário decidiu deixar a compra para depois. Candidato mantido: `usarcifra.com.br`. **Conta Resend criada durante o Pre-0** — em dev, usar o remetente de teste padrão do provedor; SPF/DKIM/DMARC só após a compra do domínio | F1.5 |
| 7 | Licença do repo | ✅ **FECHADA** | **UNLICENSED** — repo privado (SharkTrack padrão) | F0 |
| 8 | Play Store no MVP | ✅ **FECHADA** | **Não** — `.aab` interno via EAS; Play Store fica pro pós-MVP | F8 |

**Placar: 7/8 fechadas em Pre-0** (a 6 depende só do ato de comprar o domínio).

### Revisão de 2026-08-31 (remediação da F1)

A remediação da F1 (PR #12) atualizou os seguintes pontos com efeito de decisão:

- **HIBP no registro**: o plano original previa k-anonymity opt-in; a implementação integra a checagem ao fluxo de registro (controlada por `HIBP_ENABLED`, default `false`) e rejeita senhas comprometidas com 422. A frase do plano v2 permanece compatível: a checagem só acontece quando habilitada.
- **Modelo `audit_events`**: alinhado ao schema do plano (`actor_ip`, `entity_type`, `entity_id`, `before`, `after`, `occurred_at`). A política completa de audit log (retenção, consulta, exportação) segue na F1.5.
- **Row-Level Security**: `bind_current_user` publica `app.current_user_id` por transação; as policies RLS nas tabelas multiusuário serão aplicadas na F1.5, junto da política de audit log (registrado em `docs/f1-follow-ups.md`).

### Domínio — verificação de disponibilidade (DNS, agosto/2026)

Vários candidatos nominais (`cifra` em variações de TLD) estão registrados e indisponíveis. **`usarcifra.com.br`** — candidato recomendado — e **`usarcifra.app.br`** — alternativa — responderam NXDOMAIN, indicando disponibilidade provável.

> ⚠️ DNS é proxy, não fonte oficial. A confirmação real acontece no checkout do registro.br. O app continua se chamando **Cifra** independente do domínio (domínio é só infra de email/web).

---

## Consequências arquiteturais das decisões

1. **Cifra** → package Android provisório `br.com.usarcifra.app`, uma convenção válida de DNS reverso. Confirmar o identificador antes da F6; a compra do domínio não bloqueia a F0.
2. **Tudo VPS** → uma única stack Docker (api + web + Caddy/Traefik TLS) no servidor; compose prod já previsto na F7; o compose dev ganha **MinIO** (local) que espelha a API S3 do R2 em prod — zero mudança de código, só env vars (`S3_ENDPOINT`, `S3_BUCKET`, credenciais).
3. **Resend + registro.br** → SPF/DKIM/DMARC no DNS após compra; envio de recuperação de senha na F1.5; remetente sugerido: `no-reply@usarcifra.com.br`.
4. **Sentry free** → sampling configurado desde a primeira integração (F6.5); risco de quota mitigado por `traces_sample_rate` baixo.
5. **Anexos** permanecem no escopo MVP (F2 sobe com MinIO dev; R2 na F7/F8).

---

## Padrões de código (regras absolutas)

| Regra | Detalhe |
|---|---|
| **ZERO comentários no código** | Decisão do usuário (29/08/26, "não em hipótese alguma"). Vale para Python (`#`), TS/JS (`//`, `/* */`), SQL (`--`), YAML, Dockerfile, GitHub Actions. Código deve ser autoexplicativo: nomes, tipos, estrutura. |
| Docstrings | Também fora (são anotação no código). Documentação vive em type hints, ADRs, `docs/` e OpenAPI. |
| O que NÃO conta como comentário (mantém) | Commit messages (Conventional Commits), type hints, docs markdown (README/ADR/runbook), mensagens de log e erro, strings de UI, shebang. |
| Enforçamento | Revisão em cada PR + checagem no CI (F0.5): grep por marcadores de comentário com allowlist mínima (shebang, URLs com fragmento). |

---

## Checklist Pre-0 (restante)

- [x] Fechar decisões pendentes (7/8; domínio aguarda compra)
- [x] Limpeza da pasta (só v2 + roadmap)
- [x] **Validar schema com dados reais**: **CONCLUÍDO 29/08** — dataset real de lançamentos mapeado e reconciliado com saldo zerado; relatório público anonimizado em `docs/domain-validation-report.md`; gaps G1–G5 incorporados no plano v2 e roadmap
- [x] ADRs [`0001`](decisions/accepted/architecture/0001-append-only-ledger.md), [`0002`](decisions/accepted/architecture/0002-currency-per-account.md), [`0003`](decisions/accepted/architecture/0003-optimistic-locking.md) e [`0004`](decisions/accepted/security/0004-row-level-security.md) aprovados pelo usuário, promovidos e validados em 29/08
- [x] Preparar ambiente local completo: Docker 29.7.2, Compose 5.4.0, Python 3.11.16, uv 0.12.6, Node 22.23.2, pnpm 11.24.0, Expo 57/EAS 23; Android Studio 2026.1.3.7, Temurin JDK 17, SDK/ADB/emulator Android 36 instalados; AVD `Cifra_API_36` completou boot real e reportou Android 16
- [x] Criar conta Resend (29/08 — remetente de teste padrão do provedor em dev)
- [ ] Comprar domínio no registro.br (adiado pelo usuário; não bloqueia até F1.5)

### Revisão de 2026-09-01 (execução da F1.5)

A F1.5 (branch `feat/f1.5-security`) registrou as seguintes decisões de implementação:

- **Rate limit**: janela fixa no Redis via Lua atômico; `/auth/register` 3/min e `/auth/login` 5/min por identidade (IP com lista de proxies confiáveis opcional); 429 com `Retry-After`; fail-open quando o Redis está indisponível (disponibilidade de autenticação prevalece). A instrução do plano (SlowAPI) foi substituída por implementação própria atômica para manter contagem exata sob concorrência.
- **Lockout**: 5 falhas × 15 minutos com backoff exponencial, chaves `cifra:lock:*`; resposta indistinguível do login inválido; fail-open amplo.
- **Auditoria**: eventos tipados (`AuditEventType`) com sanitização de payload — chaves sensíveis mantêm a estrutura com valor `[REDACTED]`; append-only garantido por trigger no banco e policies RLS (migração 0002).
- **RLS**: role dedicada `cifra_app` NOLOGIN NOBYPASSRLS via `server_settings` do engine; escopo do usuário re-aplicado a cada transação por evento `after_begin`; fluxos pré-auth usam bypass explícito. O `get_current_user` publica o escopo antes de consultar o usuário e validar a versão de sessão (ordem é parte do contrato RLS, coberta por teste dedicado sob role real).
- **CORS**: whitelist estrita via `CORS_ALLOWED_ORIGINS`, métodos GET/POST, validação fail-closed no startup fora de teste.
- **Schemas**: `extra="forbid"` em todos os models de request (anti mass assignment).
- **Recuperação de senha**: token de 32 bytes, hash SHA-256 no Redis (TTL 15 min), consumo único por `GETDEL`; entrega via Resend opt-in (`PASSWORD_RESET_RESEND_ENABLED`); remetente de teste do provedor em dev até a compra do domínio (decisão #6 permanece adiada); respostas indistinguíveis para e-mail conhecido/desconhecido; reset concluído revoga refresh tokens e bumpa a versão de sessão.
- **Headers web**: CSP sem `unsafe-eval` e sem `unsafe-inline` (styles incluídos), HSTS 2 anos com `includeSubDomains; preload`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy` mínima; build e hidratação Next.js validados.
- **ZAP no CI**: imagem do ZAP fixada por digest imutável (não por tag); gate bloqueia findings High e falha se zero URLs examinadas; relatório preservado como artifact; `ZAP Baseline` e `Scope Isolation` entram como jobs do workflow Security sem alterar required checks remotamente nesta execução.

## Fechamento da F0 — 2026-08-29

- Monorepo pnpm + Turborepo criado com API, web, mobile e três pacotes compartilhados.
- FastAPI expõe liveness e readiness real de PostgreSQL, Redis e MinIO; teste operacional confirmou HTTP 503 com Redis indisponível e recuperação para HTTP 200.
- Docker Compose validado com cinco serviços saudáveis; volumes preservados no encerramento.
- Web consome a API exclusivamente por `@cifra/api-client`; mobile possui esqueleto funcional sem antecipar a F6.
- Testes da API, ruff, lint, typecheck, build Next.js e configuração Expo passaram.
- `imports/`, `.env`, credenciais e artefatos permanecem fora do Git.
- A regra de zero comentários e docstrings foi verificada nos arquivos de código e configuração da F0.

**Próxima fase do cronograma:** F0.5 CI/CD e Qualidade. Não iniciada nesta execução.
