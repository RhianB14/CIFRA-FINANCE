# Excecoes de seguranca ativas

Registro oficial das excecoes aplicadas aos scanners de vulnerabilidade. Toda excecao tem escopo minimo, expiracao e condicao de remocao.

## Escopo e governanca

- Arquivo de excecao: `.trivyignore-minio`, formato `CVE exp:YYYY-MM-DD`, sem comentarios, conforme a politica de zero comentarios.
- Escopo do ignore: exclusivamente o job `minio-scan` do workflow Security (campo `trivyignores`). Os jobs `image-scan` (api e web), `filesystem-scan`, o comando local `pnpm security:trivy` e o scan de arquivos versionados continuam bloqueando qualquer um destes CVEs.
- Expiracao: 2026-12-31. Apos essa data o Trivy volta a falhar com os CVEs listados, forçando reavaliacao obrigatoria.
- Responsavel pela reavaliacao: Rhian Batista.
- Condicao de remocao: publicacao de release do MinIO com correcao aplicavel. Ao sair, remover os CVEs corrigidos do `.trivyignore-minio`, atualizar a tag em `docker-compose.yml`, rebuild e re-scan zerado.

## MinIO `RELEASE.2025-09-07T16-13-09Z` (55 excecoes)

- Motivo: `RELEASE.2025-09-07T16-13-09Z` e a ultima tag publicada no Docker Hub do `minio/minio` (verificado via API do Docker Hub em 2026-08-30). As vulnerabilidades afetam componentes internos da imagem (golang.org/x/crypto, golang.org/x/net, grpc, stdlib Go, jwt-go, thrift, prometheus, libacl) sem pacote substituivel dentro da imagem.
- Prova de ausencia de correcao aplicavel: a API do Docker Hub nao retorna tag mais recente para `minio/minio`; nao existe release upstream que incorpore as correcoes; rebuild do binario do MinIO nao e viavel por ser imagem fechada do fornecedor.
- Impacto: 4 CRITICAL e 51 HIGH.
- Risco aceito: armazenamento de objetos em rede interna do compose, sem exposicao a Internet, credenciais locais ficticias, dados de desenvolvimento.

| CVE/GHSA | Severidade | Componente |
|---|---|---|
| CVE-2025-68121 | CRITICAL | stdlib |
| CVE-2026-33186 | CRITICAL | google.golang.org/grpc |
| CVE-2026-33322 | CRITICAL | github.com/minio/minio |
| CVE-2026-33419 | CRITICAL | github.com/minio/minio |
| CVE-2026-43871 | HIGH | github.com/apache/thrift |
| CVE-2025-47913 | HIGH | golang.org/x/crypto |
| CVE-2025-61726 | HIGH | stdlib |
| CVE-2025-61729 | HIGH | stdlib |
| CVE-2025-62506 | HIGH | github.com/minio/minio |
| CVE-2026-24051 | HIGH | go.opentelemetry.io/otel/sdk |
| CVE-2026-25679 | HIGH | stdlib |
| CVE-2026-25681 | HIGH | golang.org/x/net |
| CVE-2026-27136 | HIGH | golang.org/x/net |
| CVE-2026-27145 | HIGH | stdlib |
| CVE-2026-32280 | HIGH | stdlib |
| CVE-2026-32281 | HIGH | stdlib |
| CVE-2026-32283 | HIGH | stdlib |
| CVE-2026-32285 | HIGH | github.com/buger/jsonparser |
| CVE-2026-33811 | HIGH | stdlib |
| CVE-2026-33814 | HIGH | stdlib |
| CVE-2026-33818 | HIGH | stdlib |
| CVE-2026-34204 | HIGH | github.com/minio/minio |
| CVE-2026-34986 | HIGH | github.com/go-jose/go-jose/v4 |
| CVE-2026-39414 | HIGH | github.com/minio/minio |
| CVE-2026-39820 | HIGH | stdlib |
| CVE-2026-39821 | HIGH | stdlib |
| CVE-2026-39822 | HIGH | stdlib |
| CVE-2026-39828 | HIGH | golang.org/x/crypto |
| CVE-2026-39829 | HIGH | golang.org/x/crypto |
| CVE-2026-39830 | HIGH | golang.org/x/crypto |
| CVE-2026-39831 | HIGH | golang.org/x/crypto |
| CVE-2026-39832 | HIGH | golang.org/x/crypto |
| CVE-2026-39835 | HIGH | golang.org/x/crypto |
| CVE-2026-39836 | HIGH | stdlib |
| CVE-2026-39883 | HIGH | go.opentelemetry.io/otel/sdk |
| CVE-2026-40344 | HIGH | github.com/minio/minio |
| CVE-2026-41145 | HIGH | github.com/minio/minio |
| CVE-2026-41602 | HIGH | github.com/apache/thrift |
| CVE-2026-42151 | HIGH | github.com/prometheus/prometheus |
| CVE-2026-42154 | HIGH | github.com/prometheus/prometheus |
| CVE-2026-42499 | HIGH | stdlib |
| CVE-2026-42504 | HIGH | stdlib |
| CVE-2026-42508 | HIGH | golang.org/x/crypto |
| CVE-2026-46595 | HIGH | golang.org/x/crypto |
| CVE-2026-46597 | HIGH | golang.org/x/crypto |
| CVE-2026-46600 | HIGH | golang.org/x/net |
| CVE-2026-4878 | HIGH | libcap |
| CVE-2026-54369 | HIGH | libacl |
| CVE-2026-56852 | HIGH | golang.org/x/text |
| CVE-2026-56853 | HIGH | stdlib |
| CVE-2026-56854 | CRITICAL | golang.org/x/crypto |
| CVE-2026-56858 | HIGH | stdlib |
| CVE-2026-56859 | HIGH | stdlib |
| CVE-2026-56860 | HIGH | stdlib |
| CVE-2026-56862 | HIGH | stdlib |
| GHSA-hrxh-6v49-42gf | HIGH | google.golang.org/grpc |

Total: 55 excecoes ativas.

### Revisão de 2026-09-01 (F1.5)

Reverificado o Docker Hub em 2026-09-01: a tag mais recente de `minio/minio` continua sendo `RELEASE.2025-09-07T16-13-09Z` (última atualização 2025-09-07). A condição de remoção (publicação de release com correção aplicável) não se realizou. A exceção permanece inalterada: mesmo escopo (job `minio-scan` exclusivamente), mesma expiração (2026-12-31) e mesma lista de CVEs. Sem ampliação e sem renovação.

## Historico: excecoes da imagem web removidas nesta correcao

As 4 excecoes de `.trivyignore-web` (tar, brace-expansion, ip-address, picomatch — internos do npm embarcado) foram REMOVIDAS em 2026-08-30. A justificativa anterior ("somente build tool") estava incorreta: o npm e o pnpm globais permaneciam na imagem executada que serve a aplicacao. Correcao real: o Dockerfile web passou a usar o pnpm standalone 11.24.0 (binario unico musl, tar >= 7.5.22, sem brace-expansion nem ip-address embutidos) e remove o npm da imagem final. Re-scan da imagem sem ignorefile: 0 findings HIGH/CRITICAL. O arquivo `.trivyignore-web` foi excluido do repositorio.
