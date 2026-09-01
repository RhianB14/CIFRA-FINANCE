# Cifra

Cifra é um controle financeiro pessoal com web em Next.js, aplicativo Android em Expo e API FastAPI. A F0 estabelece o monorepo, os serviços locais e os contratos mínimos de saúde. A F1 adiciona autenticação multiusuário: JWT access/refresh com rotação e detecção de reutilização, Argon2id, 2FA por TOTP com backup codes e contexto de Row-Level Security.

## Pré-requisitos

- Docker Desktop 29+
- Docker Compose 5+
- Node.js 22+
- pnpm 11.24.0 instalado globalmente
- Python 3.11+
- uv 0.12+
- Android Studio, SDK Android 36 e JDK 17 para emulação local

Neste ambiente, use o pnpm global instalado por npm. Não use Corepack: o wrapper local está quebrado por conversão de caminho MSYS.

## Configuração inicial

No PowerShell, na raiz do repositório:

```powershell
Copy-Item .env.example .env
pnpm install
cd apps/api
uv sync
```

Alternativa em Bash para o arquivo de ambiente:

```bash
cp .env.example .env
```

Os valores de `.env.example` são exclusivamente locais e fictícios. O arquivo `.env` não é versionado.

## Desenvolvimento sem Docker

Na raiz:

```bash
pnpm dev
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

`pnpm lint` executa lint real por workspace: ESLint em `apps/web`, `apps/mobile` e nos três pacotes de `packages/`, além de Ruff em `apps/api`.

`pnpm typecheck` executa `tsc --noEmit` nos workspaces TypeScript.

`pnpm test` executa testes reais via Turborepo em quatro workspaces: pytest na API FastAPI, Vitest no web, Jest no mobile e Vitest no `@cifra/api-client`. Qualquer falha interrompe o comando com exit code diferente de zero. A task `test` do Turbo roda sem cache para sempre executar os testes de verdade.

`pnpm test:coverage` executa a cobertura da API com branch coverage, mínimo total de 70% e mínimo de 85% em `apps/api/app/services/`.

`pnpm verify` executa o gate unificado obrigatorio: lint, format checks, zero comentarios com seus testes, mypy strict, typecheck, testes, coverage, build web, scan gitleaks nao vazio dos arquivos rastreados, scan gitleaks do historico Git alcancavel e Expo Doctor. Qualquer falha interrompe o comando imediatamente e os scans falham se examinarem zero arquivos, zero commits ou zero bytes. As auditorias de dependencias e os scanners pesados sao executados separadamente por `pnpm run security:dependencies` e `pnpm run security:trivy`.

`uvx pre-commit==4.6.2 install` instala os hooks de commit e `uvx pre-commit==4.6.2 install --hook-type commit-msg` instala o commitlint.

`pnpm build` compila os workspaces que possuem build.

## API

```bash
cd apps/api
uv run uvicorn app.main:app --reload
uv run pytest -q
uv run ruff check .
pnpm --filter @cifra/api openapi:check
```

## Autenticação

Endpoints da F1, todos sob `/auth` (spec autoritativa em `docs/api/openapi.yaml`, servida em `/docs` pela API):

| Endpoint | Função |
|---|---|
| `POST /auth/register` | Cria usuário e retorna par de tokens |
| `POST /auth/login` | Retorna par de tokens; com 2FA ativo retorna `challenge_id` (200) |
| `POST /auth/2fa/challenge` | Troca `challenge_id` + código TOTP/backup por tokens |
| `POST /auth/refresh` | Rotaciona o refresh token; reuso de token revogado revoga a família |
| `POST /auth/logout` | Revoga a sessão apresentada |
| `GET /auth/me` | Dados do usuário autenticado (Bearer); rejeita contas desativadas (401) |
| `POST /auth/2fa/setup` | Inicia enrollment TOTP (URI otpauth + QR) |
| `POST /auth/2fa/verify` | Confirma o código e retorna backup codes de uso único |
| `POST /auth/2fa/disable` | Desativa o 2FA (exige senha e código/backup válido) |

Access token dura 15 minutos (HS256, claims `iss`, `aud`, `typ`, `jti`, `sub`, `sv` — inteiro estrito ≥ 1, sem valor padrão). Refresh dura 30 dias, é rotacionado a cada uso e só existe no banco como SHA-256. Reuso de refresh revogado revoga toda a família e invalida as sessões do usuário via versão de sessão durável no PostgreSQL publicada no Redis após o commit; a API responde 503 se o Redis estiver indisponível (fail-closed). Login de usuário inativo é indistinguível de credenciais inválidas e contas desativadas não autenticam, não rotacionam refresh e não consomem challenges. Senhas em Argon2id com rehash transparente no login; o registro consulta o HIBP k-anonymity quando `HIBP_ENABLED=true` e rejeita senhas vazadas; falha do HIBP com política fail-closed responde 503 sem persistir nada. Segredos TOTP são criptografados com Fernet (`TOTP_ENCRYPTION_KEY`) e os backup codes são HMAC-SHA256 com pepper independente (`BACKUP_CODE_PEPPER`); chave JWT, chave Fernet e pepper são validados no startup em tamanho, formato e independência mútua. A janela TOTP é simétrica (±1 janela por padrão, `TOTP_DRIFT_SECONDS // TOTP_PERIOD`) com antirreplay por passo. Desativar o 2FA exige senha e segundo fator. Ativar ou desativar o 2FA encerra as sessões anteriores. Rate limiting e account lockout ficam para a F1.5.

Para gerar as chaves locais:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

As três variáveis são obrigatórias fora de ambiente de teste; a API recusa iniciar sem elas (`ENVIRONMENT` diferente de `test` exige chaves e pepper com tamanho e independência suficientes).

## Docker Compose

No PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
docker compose down
```

`docker compose down` preserva os volumes nomeados. Para apagar dados locais deliberadamente, use `docker compose down -v`.

A imagem do MinIO está fixada em `minio/minio:RELEASE.2025-09-07T16-13-09Z`, a última imagem oficial publicada no Docker Hub. O projeto MinIO Community Edition foi arquivado pelo fornecedor e não publica mais imagens; a correção do CVE-2025-62506 saiu apenas em código-fonte. O uso permanece restrito ao desenvolvimento local com credenciais fictícias e sem dados reais. A substituição por alternativa mantida deve ser decidida antes da F2; a produção já usa Cloudflare R2 por decisão da Pre-0.

## URLs e portas

| Serviço | URL/porta |
|---|---|
| Web via Docker Compose | http://localhost:13000 |
| API OpenAPI via Docker Compose | http://localhost:18000/docs |
| API liveness via Docker Compose | http://localhost:18000/health/live |
| API readiness via Docker Compose | http://localhost:18000/health/ready |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| MinIO API | http://localhost:9000 |
| MinIO console | http://localhost:9001 |

O readiness da API consulta PostgreSQL, Redis e o endpoint `/minio/health/ready` do MinIO. Ele retorna HTTP 503 se qualquer dependência necessária estiver indisponível.

## Web

```bash
pnpm --filter @cifra/web dev
pnpm --filter @cifra/web lint
pnpm --filter @cifra/web typecheck
pnpm --filter @cifra/web build
```

A aplicação web acessa a API somente pelo pacote `@cifra/api-client`.

O arquivo `apps/web/next-env.d.ts` é gerado automaticamente pelo Next.js e não é versionado, porque o conteúdo gerado inclui comentários do framework e o projeto proíbe comentários em arquivos versionados. Em um clone limpo, instalação, typecheck e lint funcionam antes de o arquivo existir; `pnpm build` o gera automaticamente e conclui o fluxo sem intervenção manual.

## Mobile

```bash
pnpm --filter @cifra/mobile dev
pnpm --filter @cifra/mobile android
pnpm --filter @cifra/mobile lint
pnpm --filter @cifra/mobile typecheck
pnpm --filter @cifra/mobile validate
pnpm --filter @cifra/mobile exec expo install --check
```

`expo install --check` valida se as dependências do app seguem as versões esperadas pelo SDK Expo instalado e deve terminar com exit code zero.

O emulador local de referência é `Cifra_API_36`. Para Android Emulator com a API via Compose, `EXPO_PUBLIC_API_URL` usa `http://10.0.2.2:18000`. O package provisório é `br.com.usarcifra.app` e deve ser confirmado antes da F6.

A F0 contém somente a tela inicial e a preparação do cliente da API. Offline-first, autenticação, biometria e telas financeiras pertencem a fases posteriores.

## Pacotes compartilhados

- `@cifra/shared-types`: tipos mínimos de health e status
- `@cifra/api-client`: cliente tipado dos endpoints de health
- `@cifra/domain-rules`: fundação neutra, sem regras financeiras antecipadas

## Dados locais em imports

A pasta `imports/` contém extratos e documentos financeiros estritamente locais. Ela é ignorada integralmente pelo Git e não deve ser enviada, copiada ou versionada. Para preparar outra máquina, crie manualmente uma pasta `imports/` vazia.

## Decisões

Os ADRs oficiais ficam em `docs/decisions/accepted/`. A decisão 0001 é a fonte oficial do ledger append-only. Não existe ADR duplicada em `docs/adr/`.
