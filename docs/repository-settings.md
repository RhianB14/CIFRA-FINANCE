# Configuração futura do repositório GitHub

Esta configuração depende de um repositório remoto e permanece pendente até autorização explícita.

## Branch `main`

Crie um ruleset para `main` com:

- pull request obrigatório;
- pelo menos uma aprovação;
- aprovação anterior invalidada por novos commits;
- todas as conversas resolvidas;
- branch atualizada antes do merge;
- force-push bloqueado;
- deleção da branch bloqueada;
- administradores sujeitos às regras quando possível;
- merge somente após os checks obrigatórios.

## Checks obrigatórios

Selecione exatamente:

- `Quality`;
- `Test API`;
- `Test TypeScript`;
- `Build and Expo`;
- `Integration`;
- `Dependency Audit`;
- `Secret Scan`;
- `Filesystem and Configuration Scan`;
- `Image Scan`;
- `MinIO Image Scan`.

Os nomes só podem ser confirmados após a primeira execução real no GitHub. Não selecione checks inexistentes antes disso.

## Dependabot e auto-merge

Crie as labels `dependencies`, `javascript`, `python`, `github-actions` e `docker`. Dependabot abre atualizações semanais patch/minor e bloqueia majors. Auto-merge pode ser ativado somente para patch/minor depois de todos os checks, sem vulnerabilidades e com branch protection ativa. A ativação remota não foi realizada.

## Segurança

Vulnerabilidades High e Critical bloqueiam. Uma exceção deve ser versionada em arquivo específico, identificar componente e vulnerabilidade, justificar tecnicamente, ter responsável, prazo de expiração e escopo mínimo. Não use exceção para esconder resultado.

## Release Please

O workflow cria futuramente PR de release e usa Conventional Commits para atualizar `CHANGELOG.md`. A criação de tags e releases depende de merge do PR de release no GitHub. Nenhuma release ou tag é criada localmente durante a F0.5.
