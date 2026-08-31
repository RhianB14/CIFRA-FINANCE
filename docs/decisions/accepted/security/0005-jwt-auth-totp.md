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

- Access JWT (HS256, 15 min) com claims `iss`, `aud`, `typ`, `jti`, `sub` e `sv` obrigatórios; algoritmo fixado e `alg=none` rejeitado.
- Refresh token JWT de 30 dias cujo `jti` só existe no banco como SHA-256 (`jti_hash`); cada uso emite um novo token da mesma família e marca o anterior com `revoked_at`/`replaced_by`.
- Reutilização de refresh revogado revoga todos os refreshes do usuário e incrementa `cifra:session-version:<user>` no Redis; `sv` menor que a versão global é rejeitado.
- Logout revoga a sessão apresentada; o access expira pelo TTL.
- Senhas em Argon2id (`argon2-cffi`), política de comprimento e HIBP k-anonymity opt-in.
- Segundo fator TOTP (pyotp) com drift de ±1 janela e antirreplay por passo; secret criptografado com Fernet (`totp_encryption_key`) e `totp_pending_secret_encrypted` durante o enrollment.
- Backup codes: 10 códigos `XXXX-XXXX`, somente SHA-256 no banco, consumo atômico via `UPDATE ... WHERE used_at IS NULL RETURNING`.
- Login com 2FA ativo devolve `challenge_id` de uso único (Redis, TTL 300 s) e exige `/auth/2fa/challenge`.
- Falha de Redis é fail-closed: `SessionStoreUnavailableError` rejeita a requisição em vez de degradar a checagem de revogação.
- `get_current_user` injeta `set_config('app.current_user_id', ..., true)` para RLS (ADR 0004).

## Rationale

Rotação com detecção de reutilização dá revogação de família inteira a partir de um roubo detectado, sem sessões curtas demais. Armazenar apenas hashes de `jti` e de backup codes limita o dano de vazamento do banco. Fail-closed mantém a garantia de revogação mesmo sob indisponibilidade do Redis.

## Alternatives considered

- Sessões opacas server-side: revogação simples, mas custa lookup por requisição e complica clientes existentes.
- Refresh com cookie httpOnly: mitigaria XSS, mas o contrato atual da API é client-side (web Next.js e Expo), e cookies de terceiros entre origens são complexos no Expo.
- TOTP sem janela de drift: rejeitará códigos legítimos em relógios levemente defasados; ±1 janela com antirreplay equilibra usabilidade e segurança.

## Consequences

- A versão de sessão (`sv`) passa a fazer parte de todo access token; `bump_global_version` invalida tokens antigos imediatamente.
- Redis torna-se dependência crítica do caminho de autenticação.
- Rate limiting e account lockout ficam para a F1.5 e se apoiam nas mesmas chaves de usuário no Redis.
