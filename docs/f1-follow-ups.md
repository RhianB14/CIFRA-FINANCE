# F1 Follow-ups

Registro de problemas descobertos durante a remediação da F1 (PR #12) que estão fora do escopo autorizado das seções 1.1–1.12 e, por regra do brief, não foram corrigidos nesta rodada.

## 1. Policies de Row-Level Security ausentes na migração

- **Descoberto em:** 2026-08-31, durante a seção 1.12 (teste de ciclo de migrações em `tests/security/`).
- **Situação:** `app.core.db.bind_current_user` publica `app.current_user_id` por transação (`set_config(..., true)`), mas a migração `0001_initial_f1` não cria nenhuma policy RLS. Verificação no banco de desenvolvimento confirma `relrowsecurity = false` em `users`, `refresh_tokens`, `backup_codes` e `audit_events` e nenhuma linha em `pg_policies`.
- **Impacto:** o isolamento por linha previsto para a fase multiusuário não está ativo no nível do banco. Hoje o isolamento depende exclusivamente das queries dos services (sempre filtram por `user_id` do token).
- **Correção prevista:** F1.5 ("Segurança de base" no roadmap), que já lista "RLS Postgres" no escopo, junto da política completa de audit log.
- **Regra respeitada:** nenhum gate foi reduzido e nenhuma correção fora do escopo 1.1–1.12 foi aplicada.
