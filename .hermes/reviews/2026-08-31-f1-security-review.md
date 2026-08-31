# F1 Security Remediation Review — 2026-08-31

**PR:** #12 (`RhianB14/CIFRA-FINANCE`)
**Branch:** `feat/f1-auth`
**Base de remediação:** `ac8a1216e68b09f075b93922167f809aadd553dc`
**Regra de entrega:** PR aberto para revisão humana, sem merge, force-push ou reescrita dos commits publicados.

## Resumo executivo

As doze falhas autorizadas nas seções 1.1–1.12 foram tratadas por TDD, com um commit RED e um commit GREEN por item. A rodada adicionou 26 commits antes deste relatório: 24 commits para os doze itens, um para o OpenAPI determinístico e um para a reconciliação documental.

A validação local consolidada executou `pnpm verify` com saída `verify-exit=0`: 177 testes da API passaram, a cobertura total da API foi 91,17%, os scans de secrets em arquivos e histórico ficaram limpos e o Expo Doctor aprovou 21/21 checks. A stack completa foi reconstruída a partir do HEAD e validada por health checks e smoke HTTP real; os resultados estão no item 38.

## Commits da remediação

| Item | RED | GREEN |
|---|---|---|
| 1.1 | `0c4b97c` | `093ff9b` |
| 1.2 | `68980c0` | `5ee8e0b` |
| 1.3 | `5b1f356` | `e0ded36` |
| 1.4 | `fa35ad3` | `67e6193` |
| 1.5 | `711c455` | `d217bbb` |
| 1.6 | `258bb74` | `d69c672` |
| 1.7 | `f89234e` | `36abdf3` |
| 1.8 | `1ecd40a` | `1bfe154` |
| 1.9 | `cda3b66` | `6e3f175` |
| 1.10 | `fcf2a92` | `0edbdcc` |
| 1.11 | `fc3fd2e` | `22f53bb` |
| 1.12 | `80e156a` | `0d86bb0` |
| OpenAPI | — | `174aa76` |
| Documentação | — | `93fb303` |

## Checklist final — 38 itens

### 1. Escopo e segurança

1. **Branch correta:** trabalho realizado em `feat/f1-auth`, nunca em `main`.
2. **Histórico preservado:** somente commits normais; sem rebase público, amend de commit publicado ou force-push.
3. **Escopo preservado:** nenhuma implementação de rate limiting, account lockout, ZAP, headers web ou política completa de audit log.
4. **Dados protegidos:** nenhum conteúdo de `imports/` ou `docs/domain-validation.csv` foi lido ou publicado; nenhuma credencial, chave TOTP ou backup code aparece neste relatório.
5. **Gates preservados:** nenhum gate ou threshold de cobertura foi reduzido; o CI recebeu apenas um passo adicional de downgrade e re-upgrade das migrações.

### 2. Itens 1.1–1.12

6. **1.1 — rotação atômica:** revoke, emissão e vínculo `replaced_by` ocorrem na mesma transação; `replaced_by` possui FK real.
7. **1.1 — prova negativa:** concorrência e visibilidade entre conexões usam PostgreSQL e Redis reais em `tests/integration/test_rotation.py`.
8. **1.2 — session version durável:** `users.session_version` é autoritativa no PostgreSQL; o Redis é publicado somente após commit.
9. **1.2 — fail-closed:** indisponibilidade do Redis em acesso ou refresh retorna 503, sem aceitar sessão não verificável.
10. **1.3 — ativação 2FA:** ativar TOTP registra o step usado, revoga refresh tokens anteriores e incrementa a session version na transação do caso de uso.
11. **1.3 — antirreplay:** o código usado para confirmar a ativação não pode ser reutilizado.
12. **1.4 — desativação 2FA:** exige senha atual e um segundo fator válido; senha ou fator inválido aborta sem persistir mudança parcial.
13. **1.5 — backup codes:** hashes usam HMAC-SHA256 com `BACKUP_CODE_PEPPER` independente e validado com no mínimo 32 bytes.
14. **1.5 — independência criptográfica:** o teste prova que o mesmo código com peppers diferentes produz hashes diferentes.
15. **1.6 — HIBP no registro:** o cliente k-anonymity está integrado ao registro e rejeita senha comprometida com 422.
16. **1.6 — privacidade HIBP:** somente o prefixo SHA-1 de cinco caracteres é enviado, com `Add-Padding: true`; o transporte é injetável para testes.
17. **1.7 — Argon2id:** login bem-sucedido rehasha hashes legados quando `needs_rehash` indica parâmetros obsoletos.
18. **1.8 — OAuth2:** login aceita `application/x-www-form-urlencoded` por `OAuth2PasswordRequestForm`; 401 protegido inclui `WWW-Authenticate: Bearer`.
19. **1.9 — enumeração:** usuário inexistente passa por verificação Argon2 com hash dummy cacheado para reduzir diferença de timing.
20. **1.9 — corrida de registro:** violação UNIQUE concorrente é convertida em 409 após rollback, nunca em 500.
21. **1.10 — TOTP via Settings:** issuer, período e drift vêm de `Settings`; a chave Fernet inválida é rejeitada no startup fora dos ambientes isentos.
22. **1.10 — QR:** `/auth/2fa/setup` retorna URI otpauth e QR data URI no contrato OpenAPI.
23. **1.11 — AuditEvent:** modelo e migração usam `actor_ip`, `entity_type`, `entity_id`, `before`, `after` e `occurred_at` conforme o plano mestre.
24. **1.11 — usuário inativo:** `User.is_active` existe e `get_current_user` rejeita conta inativa com 401.
25. **1.12 — Alembic nos testes:** fixtures de auth routes, inactive user e rotation criam schema por `alembic upgrade head`; não há `create_all` em `apps/api/tests`.
26. **1.12 — ciclo de migração:** `tests/security/test_migrations_secure.py` prova upgrade, downgrade e upgrade novamente; o CI repete downgrade→upgrade antes da cobertura.

### 3. OpenAPI, docs e boundaries

27. **OpenAPI autoritativo:** `docs/api/openapi.yaml` é a fonte determinística na raiz do repositório.
28. **JSON removido:** `apps/api/docs/openapi.json` foi removido e o diretório não é recriado.
29. **Drift check:** exportação e teste comparam a aplicação ao YAML autoritativo; `pnpm --filter @cifra/api openapi:check` continua no CI.
30. **README:** documentação aponta para o YAML, registra HIBP no registro, OAuth2 form, QR, disable com senha e rejeição de usuário inativo.
31. **Roadmap e decisões:** F1 está reconciliada com 177 testes locais, PR aberto e revisão humana pendente; checks remotos documentados com nomes reais.
32. **Follow-up fora de escopo:** ausência de policies RLS foi registrada em `docs/f1-follow-ups.md`, sem antecipar F1.5.
33. **Boundary de registro:** user, access e refresh são preparados e persistidos sob um único commit; corrida UNIQUE faz rollback.
34. **Boundary de 2FA:** confirmação, backup codes, revogação e session version compartilham a transação do caso de uso; disable é flush-only no service e commitado pelo router.
35. **Boundary de rotação:** sucesso é atômico; no reuse, revogação e bump são commitados antes da publicação pós-commit no Redis.

### 4. Validação e entrega

36. **Qualidade consolidada:** `pnpm verify` terminou com exit 0; a suíte API passou 177/177 com cobertura total de 91,17%; ruff, mypy strict, Prettier, zero-comments, build e testes TypeScript passaram dentro do gate.
37. **Riscos residuais e pendências:** policies RLS continuam ausentes e estão explicitamente adiadas para F1.5; account lockout, rate limiting, ZAP, headers web e política completa de audit log permanecem fora do escopo; o modelo `AuditEvent` está alinhado, mas os fluxos ainda não gravam a política completa de eventos.
38. **Integração e estado de entrega:** imagens `api` e `web` reconstruídas a partir do HEAD; cinco serviços healthy; `/health/live`, `/health/ready` e Web responderam 200. Em banco dev, a migração 0001 antiga já estava marcada como aplicada, então foi executado o ciclo real downgrade base→upgrade head antes do smoke. `scripts/auth_smoke.py` passou registro 201, login 200, `/me` 200, refresh 200, replay 401, logout 204 e refresh pós-logout 401 (`SMOKE-OK`). O branch foi publicado sem force-push, a descrição do PR #12 foi atualizada e os 11 checks GitHub concluíram com sucesso no head `c209137`; o PR permaneceu aberto, não-draft e sem merge.

## Evidências locais

- `pnpm verify`: `verify-exit=0`.
- Pytest de cobertura: `177 passed in 96.48s`.
- Cobertura total API: `91.17%`.
- Secret scan de arquivos rastreados: limpo (`files=148`).
- Secret scan do histórico: limpo (`commits=45`, `objects=645`).
- Expo Doctor: `21/21 checks passed`.
- Compose: `api`, `web`, `postgres`, `redis` e `minio` healthy após rebuild.
- Smoke HTTP real: `SMOKE-OK` após downgrade base→upgrade head no banco dev.
- Pre-commit: todos os 26 commits de remediação e o fix de compatibilidade do Compose pousaram após os hooks; o commit deste relatório também deve passar os mesmos hooks.
