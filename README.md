# Cifra

Cifra é um controle financeiro pessoal com web em Next.js, aplicativo Android em Expo e API FastAPI. A F0 estabelece o monorepo, os serviços locais e os contratos mínimos de saúde, sem antecipar autenticação ou domínio financeiro.

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

`pnpm test` executa os testes reais da API FastAPI via Turborepo: o workspace `@cifra/api` roda `uv run pytest -q`, e qualquer falha do pytest interrompe o comando com exit code diferente de zero. A task `test` do Turbo roda sem cache para sempre executar os testes de verdade. A suíte atual contém os três testes de comportamento da API e um teste adicional de isolamento dos overrides. Nesta fase não existem testes de front-end; a suíte Jest completa entra na F0.5.

`pnpm build` compila os workspaces que possuem build.

## API

```bash
cd apps/api
uv run uvicorn app.main:app --reload
uv run pytest -q
uv run ruff check .
```

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
