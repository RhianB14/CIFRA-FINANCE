# Relatório de validação do domínio — Cifra

**Status:** APROVADO COM AJUSTES DE SCHEMA
**Critério:** ≥30 lançamentos mapeados
**Método:** validação executada em um dataset privado local; números abaixo são sintéticos e existem apenas para preservar a forma da evidência. Nenhum dado financeiro real é publicado neste repositório.

O dataset de lançamentos (`docs/domain-validation.csv`) e os arquivos brutos (`imports/`) permanecem estritamente locais e fora do controle de versão, porque contêm dados financeiros pessoais; apenas este relatório agregado é versionado.

## Fontes analisadas

| Arquivo | Tipo | SHA-256 |
|---|---|---|
| extrato de conta (CSV) | conta corrente, período de aproximadamente 1 mês | sintético — não publicado |
| fatura de cartão (PDF) | cartão de crédito, fechamento mensal | sintético — não publicado |

Os hashes SHA-256 reais dos arquivos privados são usados apenas localmente, como base de deduplicação (`import_batches`), e não são publicados.

## Resumo quantitativo (sintético)

### Conta

| Indicador | Resultado |
|---|---:|
| Lançamentos não nulos | ≥30 |
| Créditos | reconciliado |
| Débitos | reconciliado |
| Variação líquida | 0,00 |

O extrato analisado inicia e termina com saldo zero e a soma aritmética foi reconciliada: créditos menos débitos igual a zero.

### Cartão

| Campo | Resultado |
|---|---|
| Período de consumo | mês anterior ao fechamento |
| Fechamento | configurável por cartão |
| Vencimento | configurável por cartão |
| Total da fatura | reconciliado com a soma dos lançamentos |

A compra realizada durante o período de consumo de um mês pertence corretamente à fatura fechada no mês seguinte, com vencimento posterior. Isso valida a regra de competência por intervalo de fechamento do plano v2.

## Casos de domínio confirmados

1. **Conta corrente e poupança como contas separadas.** Baixas automáticas da poupança devem formar um par de transferência quando os dois extratos estiverem disponíveis.
2. **Transferência própria não pode ser inferida apenas pela descrição.** Envios e recebimentos via PIX podem ser receita/despesa ou movimentação entre contas do mesmo usuário.
3. **Pagamento por QR Code perde o nome do estabelecimento no CSV analisado.** A categoria precisa ser confirmada manualmente ou enriquecida por outra fonte.
4. **Fatura possui período, fechamento e vencimento reais.** `card_invoices` materializada está correta.
5. **Pagamento da fatura anterior aparece como crédito na fatura seguinte.** O sistema precisa registrar pagamentos e alocá-los explicitamente a uma fatura.
6. **Pagamento mínimo, rotativo e parcelamento de fatura existem no documento**, mesmo sem terem sido usados. O MVP não precisa reproduzir ofertas do emissor, mas precisa representar encargos e saldo carregado quando ocorrerem.
7. **Fechamento e vencimento em dias distintos por cartão** confirma que os dias são configuráveis por cartão, não globais.

## Gaps encontrados e ajustes obrigatórios

### G1 — Proveniência e deduplicação de importações

O schema v2 não registra de qual arquivo veio cada lançamento. Reimportar o mesmo CSV/PDF poderia duplicar dados.

**Ajuste:** criar `import_batches` com hash SHA-256, tipo da fonte, período e status. Adicionar em `transactions`: `import_batch_id`, `external_id`, `raw_description` e `source_document_number`. Usar índice único parcial por usuário/fonte/identificador quando o banco fornecer ID; fallback para fingerprint determinístico.

### G2 — Conciliação com saldo informado pelo banco

O schema calcula saldo pelo ledger, mas não guarda os pontos de saldo do extrato. Sem isso, é impossível provar que o importado corresponde ao banco.

**Ajuste:** criar `account_balance_snapshots` com `account_id`, data/hora, saldo em centavos, origem e lote de importação. A reconciliação compara o saldo calculado no mesmo ponto temporal com o snapshot.

### G3 — Pagamento de fatura e alocação

Atualizar apenas `card_invoices.paid_cents` perde histórico e dificulta múltiplos pagamentos, pagamentos parciais, estornos e idempotência.

**Ajuste:** criar `invoice_payments` append-only, ligado à fatura e à transação de saída da conta. `paid_cents` passa a ser derivado pela soma dos pagamentos válidos, podendo existir como cache materializado reconciliável.

### G4 — Encargos do cartão

O enum atual não distingue juros, multa, IOF e tarifa. Tudo poderia cair em `adjustment`, mas relatórios financeiros ficariam opacos.

**Ajuste:** manter `transaction.type=card_charge` e adicionar `card_charge_kind: purchase|interest|late_fee|iof|withdrawal_fee|other`. Não modelar ofertas de financiamento do emissor no MVP.

### G5 — Classificação pendente por falta de contraparte

Lançamentos PIX com descrição genérica não oferecem evidência suficiente para atribuir categoria específica.

**Ajuste:** suportar `category_id=NULL` como "A classificar" e uma fila de revisão pós-importação. Nunca inventar a categoria automaticamente sem confiança explícita.

## Invariantes validadas

- `saldo_final = saldo_inicial + Σ(créditos) − Σ(débitos)`.
- Transferência entre contas próprias deve somar zero no consolidado quando o par estiver reconciliado.
- Compra no cartão altera exposição/fatura, não saldo de conta.
- Pagamento de fatura altera saldo da conta e reduz a dívida da fatura, sem contar como despesa de consumo novamente.
- Reimportar a mesma fonte não pode criar novos lançamentos.
- `card_invoice.total_cents = Σ(compras + encargos − estornos)` da competência.
- `card_invoice.paid_cents = Σ(invoice_payments válidos)`.

## Limitações da amostra

A amostra não contém compra parcelada ativa, estorno, assinatura recorrente, juros efetivamente cobrados, pagamento parcial efetivo ou compra internacional. Esses casos permanecem cobertos pelos testes sintéticos da F4 e não podem ser alegados como empiricamente validados por estes arquivos.

## Conclusão

O modelo central do plano v2 é compatível com um dataset real de lançamentos, mas deve incorporar G1–G5 antes da implementação do domínio. Com esses ajustes, o schema suporta extratos reais sem ambiguidade contábil e com reconciliação auditável.
