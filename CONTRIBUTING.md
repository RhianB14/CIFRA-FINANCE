# Contribuindo com o Cifra

## Ambiente

Use Node.js 22.23.2, pnpm 11.24.0, Python 3.11, uv 0.12.6, Docker Desktop 29+ e Docker Compose 5+. Execute `pnpm install --frozen-lockfile` na raiz e `uv sync --frozen` em `apps/api`.

Instale os hooks com `uvx pre-commit==4.6.2 install` e `uvx pre-commit==4.6.2 install --hook-type commit-msg`.

## Branches e commits

Crie branches a partir de `main` usando `feat/`, `fix/`, `chore/` ou `ci/`. Commits seguem Conventional Commits, como `feat: add account endpoint`, `fix: preserve readiness cleanup` e `ci: establish quality gates`.

O hook `commit-msg` rejeita mensagens fora desse padrão.

## Comandos obrigatórios

Antes de abrir um PR, execute:

```bash
pnpm install --frozen-lockfile
pnpm ci
pnpm security:dependencies
uvx pre-commit run --all-files
```

`pnpm test` executa testes reais da API, web, mobile e api-client. `pnpm test:coverage` exige cobertura total da API de pelo menos 70% e cobertura de `apps/api/app/services/` de pelo menos 85%.

## Código e documentação

Código e configuração não podem conter comentários ou docstrings. A política cobre Python, TypeScript, JavaScript, CSS, SQL, YAML, Dockerfiles e GitHub Actions. Use nomes, tipos e módulos autoexplicativos. Documentação explicativa pertence a Markdown, ADRs, OpenAPI e runbooks.

`pnpm zero-comments` aplica a política aos arquivos versionados relevantes e `pnpm zero-comments:test` valida o detector.

## Secrets e dados financeiros

Nunca versione `.env`, chaves, certificados, tokens, PDFs, extratos ou arquivos em `imports/`. `docs/domain-validation.csv` contém dados financeiros locais e deve permanecer ignorado. `.env.example` contém somente valores fictícios conhecidos.

Execute `pnpm security:secrets` antes do PR. Exceções de segurança exigem escopo mínimo, justificativa, prazo e revisão humana.

## Pull requests

O PR deve ter descrição objetiva, escopo restrito à fase, evidência dos testes e riscos restantes. Mantenha a branch atualizada com `main`, resolva todas as conversas e aguarde os checks obrigatórios. Pelo menos uma aprovação é necessária.

## Revisão

A revisão verifica comportamento, segurança, cobertura, arquitetura, ausência de dados sensíveis e aderência à política de zero comentários. Não reduza gates para aprovar uma mudança.

## Definition of Done

Uma mudança está pronta quando:

- escopo e critérios de aceite foram atendidos;
- lint, format, mypy strict, typecheck, testes, coverage, build e segurança passaram;
- pre-commit e commitlint passaram;
- documentação foi atualizada quando necessário;
- não há tarefas com zero testes ou zero execução;
- não há comentários, docstrings, secrets ou dados financeiros versionados;
- o PR foi revisado e todos os checks obrigatórios estão verdes.
