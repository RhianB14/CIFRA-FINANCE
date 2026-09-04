# Run RUN-F4-2026-09-04-02-basedON-5cc31fa — F4 Concurrency & Reversal Uniqueness

- **Data:** 2026-09-04
- **Branch:** `feat/f4-credit-cards-invoices-installments`
- **Base main:** `cfdc4520379541aee90ad95c3481bd5ad0e3d803`
- **Head de código:** `5087147` (`fix(f4): serialize card payments and reversals`)
- **Ledger:** `.hermes/ledger/f4.md` v2026-09-04 07:06:46 -03:00

## Guarda anti-reexecução e estado inicial

- Run ID ausente do histórico e do ledger; havia WIP não commitado exatamente no whitelist do Run, auditado e continuado sem sobrescrever trabalho externo.
- `origin/main` e `origin/feat/f4-credit-cards-invoices-installments` conferidos nos SHAs declarados.
- PR #21: open, merged=false, mergeable/clean e 13/13 checks no head inicial.

## Implementação

- Concorrência real substitui o teste sequencial: duas sessões PostgreSQL independentes, `asyncio.Barrier(2)` e `asyncio.gather`.
- Locks em ordem global: cartão, contas ordenadas por UUID e fatura; refresh ocorre sob lock antes de leitura ou mutação dependente.
- Re-check de idempotência, total pago e saldo pendente ocorre após aquisição dos locks.
- Estorno usa claim append-only por `InvoicePayment(kind="reversal", reversed_by_id=payment.id)`.
- Índice único parcial `uq_invoice_payments_reversed_payment` reforça no PostgreSQL o limite de um estorno por pagamento; modelo e upgrade/downgrade da 0013 estão alinhados.
- Replay com a mesma chave retorna o estorno existente sem nova mutação; chave diferente é rejeitada.

## TDD RED→GREEN

O WIP pré-existente registrava os REDs antes da implementação:

- pagamento concorrente válido: `(96000, 1) != (92000, 2)` — lost update do pagador;
- compra/reversão concorrentes: `(-10000, 2) != (-7000, 3)` — crédito de estorno perdido;
- segundo estorno sequencial: resultado `ok` quando deveria ser rejeitado;
- dois estornos concorrentes: `['ok', 'ok']`;
- índice único ausente no catálogo.

GREEN verificado pelo Hermes principal: bateria direcionada com 21 testes, incluindo sete casos de concorrência/migração. A revisão independente identificou ausência de prova explícita do replay de estorno; o teste foi ampliado para afirmar mesmo ID, saldo/versão invariantes e ausência de nova mutação.

## Migração em banco descartável

Banco exato `cifra_f4_audit_20260904` criado do zero, migrado 0012→0013, inspecionado, downgrade 0013→0012 e novo upgrade 0012→0013. Evidências:

- `transactions_card_linkage`, `transactions_card_operation`, `transactions_installment_pair` e `transactions_installment_range`: `convalidated=true`;
- índice `uq_invoice_payments_reversed_payment`: `CREATE UNIQUE INDEX ... (reversed_by_id) WHERE reversed_by_id IS NOT NULL`;
- após downgrade, contagem do índice = 0; após re-upgrade, presente;
- `alembic check`: `No new upgrade operations detected.`;
- banco descartável excluído após a evidência.

O banco dev `cifra` não recebeu upgrade, downgrade ou DDL neste Run.

## Revisão independente

Revisor independente, somente leitura, apontou um problema de teste: o critério de replay do estorno estava afirmado no relatório sem assert explícito no teste. Corrigido no whitelist e revalidado. Nenhum defeito de produção adicional foi reportado.

## Validação local

| Gate | Resultado |
|---|---|
| Testes direcionados | 21 passed |
| Replay explícito do estorno | 1 passed; mesmo ID e snapshot de conta invariável |
| Suíte API integral | 441 passed; exit 0 |
| mypy strict app+tests | 0 erros em 143 arquivos |
| ruff check | All checks passed |
| ruff format check | 143 arquivos formatados |
| zero-comments | exit 0 |
| secrets:files | limpo, 264 arquivos |
| secrets:history | limpo, 12 commits |
| `pnpm verify` | exit 0; 441 testes API em test e coverage; cobertura global 84.25%; drift limpo; Expo Doctor 21/21 |
| Compose | build exit 0; api, postgres, redis, minio e web healthy |
| Smokes | F2-SMOKE-OK; F3-SMOKE-OK; F4-SMOKE-OK (`exposure=21001`, `available=78999`, 4 faturas, 3 reversões) |

Durante a validação houve falhas reproduzíveis do proxy Docker Desktop (`WinError 64`) em `test_session_version`, sempre verdes em execução isolada. A causa de infraestrutura foi removida recriando o relay socat com porta interna e externa 15432 e desativando negociação SSL local. O run autoritativo posterior terminou com exit 0.

## Critérios de aceitação

| Critério | Estado | Confidence |
|---|---|---|
| concorrência real e sobreposição | PROVEN | HIGH |
| 6k+6k: exatamente um sucesso | PROVEN | HIGH |
| 4k+4k: líquido 8k sem lost update | PROVEN | HIGH |
| locks determinísticos antes do estado dependente | PROVEN | HIGH |
| compra/reversão concorrentes preservam exposição | PROVEN | HIGH |
| mesma idempotency key: efeito único | PROVEN | HIGH |
| estorno sequencial e concorrente único | PROVEN | HIGH |
| unicidade PostgreSQL append-only | PROVEN | HIGH |
| replay de estorno sem nova mutação | PROVEN | HIGH |
| CHECKs válidos e ciclo 0012↔0013 | PROVEN | HIGH |
| banco dev intacto | PROVEN | HIGH |
| revisão independente | PROVEN | HIGH |
| API integral, verify e Compose/smokes | PROVEN | HIGH |
| CI remoto no novo HEAD | PENDING | LOW |

## Known unknowns

- O proxy Docker Desktop host→container apresentou `WinError 64` sob rajadas de conexões; relay socat foi recriado com portas internas/externas coerentes e `PGSSLMODE=disable` durante a validação local.
- O resultado final do CI depende do push dos commits deste Run.

## Non-verifiable claims

- Checks remotos do novo HEAD somente serão marcados após push e polling da API REST.

## Confirmações

- PR #21 não será mergeado.
- F5 não foi iniciada.
- Nenhum force push, tag, release ou deploy.
- Banco dev `cifra` não foi alterado neste Run.

VEREDITO: PARCIAL — validações finais e CI remoto ainda pendentes.
MERGE: não (não autorizado neste prompt)
