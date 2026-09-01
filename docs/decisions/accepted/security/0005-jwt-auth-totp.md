---
id: "0005"
title: Autenticação JWT com rotação de refresh e TOTP
type: security
status: accepted
date: 2026-08-31
deciders: [Rhian Batista]
summary: Access token de curta vida, refresh rotativo com detecção de reutilização, Argon2id e segundo fator TOTP com backup codes.
tags: [security, auth, jwt, totp, argon2, redis]
relates_to: ["0004"]
supersedes:
superseded_by:
---

# 0005 — Autenticação JWT com rotação de refresh e TOTP

## Context

A F1 introduz autenticação multiusuário na API. Sessões precisam sobreviver a dias sem abrir mão da revogação rápida, o segundo fator precisa ser opcional no cadastro e obrigatório no login após ativação, e nenhum secret pode residir em texto plano no banco.

## Decision

- Access JWT (HS256, 15 min) com claims `iss`, `aud`, `typ`, `jti`, `sub` e `sv` obrigatórios; algoritmo fixado e `alg=none` rejeitado. `sv` deve ser inteiro estrito maior ou igual a 1 (booleanos e strings são rejeitados).
- Refresh token JWT de 30 dias cujo `jti` só existe no banco como SHA-256 (`jti_hash`); cada uso emite um novo token da mesma família e marca o anterior com `revoked_at`/`replaced_by`. O refresh token não carrega `sv`.
- PostgreSQL é a fonte autoritativa da versão de sessão: a coluna `users.session_version` é incrementada por `bump_session_version` com `UPDATE ... RETURNING` dentro da mesma transação do caso de uso.
- O Redis é dependência de invalidação/cache da versão de sessão (`cifra:session-version:<user>`), nunca fonte da verdade. A ordem é sempre commit no PostgreSQL primeiro, publicação no Redis depois; falha de publicação não desfaz o bump e o cache é repopulado a partir do banco.
- A comparação do access token é por igualdade exata: o `sv` da claim precisa ser igual à versão vigente do usuário; qualquer diferença rejeita o token.
- Reutilização de refresh revogado revoga todos os refreshes do usuário, faz o bump durável em `users.session_version` e publica no Redis após o commit; sessões existentes morrem na próxima checagem de revogação.
- Logout revoga a sessão apresentada; o access expira pelo TTL.
- Senhas em Argon2id (`argon2-cffi`) com rehash transparente no login quando os parâmetros ficam abaixo dos vigentes; política de comprimento e HIBP k-anonymity opt-in no registro; indisponibilidade do HIBP com política fail-closed responde 503 sem persistir usuário nem tokens.
- Segundo fator TOTP (pyotp) com janela simétrica de ±1 janela (`totp_drift_seconds // totp_period`), varredura determinística de `current-drift` até `current+drift` e antirreplay por passo (`candidate_step` maior que `totp_last_step`); secret criptografado com Fernet (`totp_encryption_key`) e `totp_pending_secret_encrypted` durante o enrollment.
- Backup codes: 10 códigos `XXXX-XXXX` armazenados como HMAC-SHA256 com `BACKUP_CODE_PEPPER` independente das demais chaves; consumo atômico via `UPDATE ... WHERE used_at IS NULL RETURNING`.
- Ativação do 2FA grava o passo antirreplay, revoga todos os refresh tokens e faz bump da versão de sessão na mesma transação; desativação exige reautenticação com a senha atual mais um segundo fator válido e aplica a mesma revogação.
- Login com 2FA ativo devolve `200` com `challenge_id` de uso único, chave Redis de alta entropia, TTL 300 s e payload vinculado a `user_id`, `session_version` vigente e finalidade `login-2fa`; o consumo compara a versão exata, exigindo usuário existente e ativo com TOTP habilitado, e invalida o challenge após reuse detection, bump ou desativação do fator. Redis indisponível responde 503; payload corrompido é rejeitado sem traceback.
- `get_current_user` injeta `set_config('app.current_user_id', ..., true)` para RLS (ADR 0004).
- O startup valida simultaneamente chave JWT, chave Fernet e pepper dos backup codes: presença, formato, tamanho mínimo em bytes, independência mútua e ausência de valores de desenvolvimento em produção, além de limites numéricos de janela TOTP, TTLs e timeout HIBP.

## Rationale

Rotação com detecção de reutilização dá revogação de família inteira a partir de um roubo detectado, sem sessões curtas demais. Manter a versão de sessão no PostgreSQL garante durabilidade e uma única fonte de verdade, enquanto o Redis serve apenas para checagem rápida de invalidação. Armazenar apenas hashes de `jti`, HMACs de backup codes e segredos TOTP cifrados limita o dano de vazamento do banco. Fail-closed mantém a garantia de revogação mesmo sob indisponibilidade do Redis.

## Alternatives considered

- Sessões opacas server-side: revogação simples, mas custa lookup por requisição e complica clientes existentes.
- Refresh com cookie httpOnly: mitigaria XSS, mas o contrato atual da API é client-side (web Next.js e Expo), e cookies de terceiros entre origens são complexos no Expo.
- TOTP sem janela de drift: rejeitará códigos legítimos em relógios levemente defasados; ±1 janela com antirreplay equilibra usabilidade e segurança.
- Redis como fonte da versão de sessão: perde-se o estado em reinício do Redis e cria dois modelos concorrentes; o banco durável com cache Redis é estritamente superior.

## Consequences

- `sv` faz parte de todo access token; `bump_session_version` no banco invalida tokens antigos imediatamente, inclusive após reinício do Redis.
- Redis torna-se dependência crítica do caminho de autenticação, porém sempre como cache reconstrutível e em modo fail-closed.
- Challenges de 2FA morrem junto com a versão de sessão; nenhum challenge emitido antes de reuse detection, bump ou desativação sobrevive.
- Rate limiting e account lockout ficam para a F1.5 e se apoiam nas mesmas chaves de usuário no Redis.
