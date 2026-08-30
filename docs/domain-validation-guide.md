# Guia — Validação de schema com lançamentos reais (Pre-0)

**Objetivo:** confirmar que o schema do plano v2 (accounts, transactions, card_invoices, installments, budgets, recorrências) comporta a sua vida financeira REAL antes de escrever código. Retrabalho de schema na F2/F4 é o erro mais caro possível — este item o elimina.

## O que você me manda

Exporte **2–3 meses** de histórico (quanto mais, melhor) e solte os arquivos em:

```
dev\FINANCE PROJ\imports\
```

| Tipo | Onde exportar | Formato aceito |
|---|---|---|
| Conta corrente / poupança | app do banco → extrato → exportar CSV | CSV, OFX, ou colado no chat |
| Fatura de cartão de crédito | app do cartão (Nubank: Fatura → Exportar) | CSV ou colado |
| Carteira digital / banco digital (se usar) | extrato do app | CSV ou colado |
| Dinheiro vivo (se anotar) | pode colar uma lista informal no chat | texto livre |

Qualquer formato serve — a conversão é comigo. Se preferir, pode colar o extrato direto no chat (uma linha por lançamento).

## O que eu faço com isso

1. Parseio o(s) arquivo(s) bruto(s) e mapeio cada lançamento para o CSV canônico (`docs/domain-validation.csv`, estritamente local — é o CSV real de validação; um modelo público sintético pode ser gerado sob pedido):

| Coluna | Significado |
|---|---|
| `date` | YYYY-MM-DD |
| `description` | descrição original do banco (posso anonimizar se você quiser) |
| `amount_cents` | valor em centavos, sinalizado: **+** entrada, **−** saída |
| `source_type` | conta_corrente · poupanca · cartao · carteira_digital · dinheiro |
| `source_name` | Nubank, Itaú, Inter, PicPay… |
| `category_guess` | meu chute de categoria (alimentacao, transporte, moradia, lazer, saude, assinatura, renda, transferencia…) |
| `is_transfer` | PIX/TED/DOC/movimentação entre contas próprias |
| `is_installment` | parcela (nome com "2/3", "PARC", loja repetida em meses seguintes) |
| `is_subscription` | cobrança recorrente mensal (Netflix, Spotify, academia…) |
| `is_refund` | estorno/devolução |
| `notes` | qualquer ambiguidade que eu encontre |

2. Produzo um **relatório de validação** com:
   - Contagem por tipo, categoria e fonte;
   - Parcelamentos detectados (e se a coluna "parcela atual/total" do banco está disponível);
   - Assinaturas recorrentes detectadas (viram `recurring_transactions`);
   - Estornos detectados (validam a decisão append-only + `reverses_transaction_id`);
   - **Gaps**: tudo que aparecer no extrato e NÃO couber no schema v2 → vira ajuste no plano antes da F0.

## Critério de aceite (do roadmap)

≥ 30 lançamentos reais mapeados + relatório de validação + eventuais ajustes de schema acordados e documentados aqui ou no plano v2.

**Privacidade:** os arquivos em `imports/` ficam só na sua máquina (repo ainda não existe e será privado); posso gerar o CSV final com descrições anonimizadas — é só pedir.
