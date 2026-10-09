# Relatório de Diagnóstico das Fontes — Mercatto Varejo

**Disciplina:** Mineração de Dados · IFMT  
**Entrega:** Semana 1 — diagnóstico das quatro fontes  
**Equipe:** [preencher]  
**Data das medições:** 09/10/2026  
**Ambiente:** laboratório Docker, escala 1,0, semente 20262

## 1. Objetivo e procedimento

Este relatório descreve as fontes disponíveis para integrar o histórico de clientes da Mercatto: ERP legado em MySQL, e-commerce em PostgreSQL, atendimentos do SAC em CSV e avaliações do marketplace em NDJSON. O objetivo analítico do projeto é prever, usando o comportamento até 30/06/2025, se um cliente realizará nova compra entre 01/07/2025 e 28/09/2025.

As medições foram realizadas sobre as tabelas completas das origens e sobre todos os registros dos arquivos, sem alterar os dados. O diagnóstico foi iniciado com `00_perfilamento.py` e complementado pelo script `diagnostico_chaves.py`. As tabelas a seguir não estão sujeitas ao limite de 200.000 linhas empregado pelo perfilador original em algumas consultas.

## 2. Questão (a) — Candidatos a chave de junção e cobertura real

**Critério de cobertura.** Um registro é considerado coberto quando sua chave encontra pelo menos uma ocorrência na fonte de destino. O percentual é `100 × registros cobertos ÷ registros examinados`. Cada linha da origem é contada uma única vez, independentemente de quantas correspondências existam no destino. Ausências e duplicatas permanecem na base de cálculo. Assim, cobertura mede a possibilidade de ligação; não comprova que dois registros representam a mesma pessoa.

Para comparar representações, CPF e telefone foram reduzidos a dígitos; e-mail foi convertido para minúsculas, com remoção de espaços nas extremidades; nomes foram comparados após remoção de acentos, conversão para maiúsculas e redução de espaços consecutivos. Valores vazios não foram pareados. São critérios de comparação para o diagnóstico, sem gravação de dados transformados.

### 2.1. Identidade do cliente entre MySQL e PostgreSQL

Foram examinados **47.250 registros de `CLIENTES`** e **85.000 de `shop.customer`**. Os identificadores internos `ID_CLIENTE` e `customer_id` pertencem a sistemas diferentes: a igualdade numérica entre eles não estabelece identidade. Os candidatos presentes nos dois cadastros e suas coberturas foram:

| Candidato entre cadastros | Valores distintos em comum | Legado com correspondência / 47.250 | E-commerce com correspondência / 85.000 |
|---|---:|---:|---:|
| `CPF` ↔ `tax_id`, somente dígitos | 12.605 | 13.048 (27,61%) | 12.606 (14,83%) |
| `EMAIL` ↔ `email`, normalizados | 0 | 0 (0,00%) | 0 (0,00%) |
| `NOME` ↔ `full_name`, normalizados | 22.869 | 28.204 (59,69%) | 31.360 (36,89%) |
| `TELEFONE` ↔ `phone`, somente dígitos | 0 | 0 (0,00%) | 0 (0,00%) |

O **CPF é o principal candidato à ligação entre os cadastros**. Está preenchido em 42.827 registros do legado (90,64%) e 78.145 do e-commerce (91,94%). Há 41.400 CPFs distintos não vazios no legado e 78.142 no e-commerce; a interseção de 12.605 corresponde a 30,45% e 16,13% desses conjuntos, respectivamente. Esses percentuais sobre valores distintos complementam a cobertura por registros da tabela e usam denominadores diferentes.

A unicidade precisa ser investigada antes de uma junção: 1.427 valores de CPF se repetem no legado e 3 no e-commerce. Apenas 12.161 dos 12.605 CPFs compartilhados ocorrem uma única vez em cada cadastro. Uma junção direta por CPF produziria 13.049 pares, demonstrando que quantidade de pares não equivale a quantidade de clientes unificados. Entre os CPFs compartilhados, 1.135 (9,00%) têm dígito verificador inválido; excluí-los previamente eliminaria essas correspondências observáveis. O diagnóstico não permite afirmar que toda correspondência por CPF, válido ou inválido, identifica corretamente uma pessoa.

O nome tem cobertura maior, mas apresenta colisões: 6.758 nomes normalizados se repetem no legado e 15.477 no e-commerce. Uma junção por nome produziria 39.505 pares. Por isso, o nome pode apoiar uma investigação de identidade, mas sua igualdade isolada não é suficiente para unificar clientes. E-mail e telefone, embora preenchidos em todos os registros, não apresentam interseção entre os sistemas nesta base.

### 2.2. Ligação dos arquivos aos pedidos, clientes e produtos

No SAC, a chave de pedido é composta por **`(origem_sistema, id_pedido_origem)`**: `LEGADO` direciona a busca para `PEDIDOS.ID_PEDIDO` e `ECOM` para `shop.orders.order_id`. No JSON, **`order.ref`** já incorpora essa distinção, com os prefixos `LEG-` e `ECOM-`. A origem deve acompanhar o identificador, pois os números de pedido podem coincidir entre os sistemas.

| Candidato e destino | Registros cobertos / examinados | Cobertura |
|---|---:|---:|
| SAC: `(origem_sistema, id_pedido_origem)` → pedido na origem indicada | 96.140 / 96.140 | 100,00% |
| SAC: `cpf_cliente` → CPF em pelo menos um dos cadastros | 90.155 / 96.140 | 93,77% |
| SAC: `cpf_cliente` → cadastro indicado por `origem_sistema` | 88.535 / 96.140 | 92,09% |
| JSON: `order.ref = LEG-<id>` → `PEDIDOS.ID_PEDIDO` | 40.016 / 40.016 | 100,00% |
| JSON: `order.ref = ECOM-<id>` → `shop.orders.order_id` | 119.984 / 119.984 | 100,00% |
| JSON: `product.sku = LEG-<id>` → `PRODUTOS.ID_PRODUTO` | 40.016 / 40.016 | 100,00% |
| JSON: `product.sku = SKU-<n>` → `shop.product.sku` | 119.984 / 119.984 | 100,00% |

O SAC contém 36.527 linhas com origem `LEGADO` e 59.613 com origem `ECOM`; todas encontram seu pedido. Pelo CPF no cadastro indicado pela origem, encontram correspondência 33.672 linhas do legado (92,18%) e 54.863 do e-commerce (92,03%). Considerando qualquer um dos dois cadastros, 5.985 linhas do SAC (6,23%) ficam sem correspondência por CPF. A ligação pelo pedido tem, portanto, maior cobertura observada. Os CPFs do SAC estão preenchidos em todas as linhas, mas preenchimento não garante presença no cadastro de destino.

As 160.000 avaliações encontram um pedido por `order.ref` e um produto pela referência com prefixo. Essa medição verifica a existência das entidades separadamente; não demonstra que o produto avaliado consta entre os itens do pedido referenciado. `protocolo` e `review_id` identificam registros nas próprias fontes, mas não têm campo equivalente nos bancos para servir como ponte direta entre elas.

### 2.3. Chaves relacionais dentro de cada banco

As chaves locais também foram verificadas para sustentar a ligação dos pedidos aos clientes e dos itens aos pedidos e produtos:

| Relação e campos | Registros cobertos / examinados | Cobertura |
|---|---:|---:|
| Legado: `PEDIDOS.ID_CLIENTE` → `CLIENTES.ID_CLIENTE` | 130.000 / 130.000 | 100,00% |
| E-commerce: `orders.customer_id` → `customer.customer_id` | 280.000 / 280.000 | 100,00% |
| Legado: `ITENS_PEDIDO.ID_PEDIDO` → `PEDIDOS.ID_PEDIDO` | 391.218 / 397.086 | 98,52% |
| E-commerce: `order_item.order_id` → `orders.order_id` | 980.658 / 995.367 | 98,52% |
| Legado: `ITENS_PEDIDO.ID_PRODUTO` → `PRODUTOS.ID_PRODUTO` | 397.086 / 397.086 | 100,00% |
| E-commerce: `order_item.product_id` → `product.product_id` | 995.367 / 995.367 | 100,00% |

Há **5.868 itens sem pedido correspondente no legado** e **14.709 no e-commerce** (1,48% dos itens de cada sistema). As referências a produtos, por sua vez, encontram correspondência em todos os itens. Os IDs de produto são locais; sua igualdade numérica entre bancos não comprova equivalência comercial entre produtos.

## 3. Questão (b) — Heterogeneidade semântica

[A desenvolver: ao menos três casos com evidência numérica.]

## 4. Questão (c) — Reconciliação dos valores dos pedidos

[A desenvolver: comparar os totais com a soma dos itens, frete e desconto em cada origem.]

## 5. Questão (d) — Anomalias e limites do diagnóstico

[A desenvolver: quantificar anomalias e explicar quais dependem da integração.]

## 6. Questão (e) — Grão pretendido das tabelas-fato

[A desenvolver: declarar a unidade representada por cada linha das tabelas-fato.]

## Referências e evidências locais

- Enunciado: `Projeto_Pratico_ETL_Mercatto.pdf`, seção 3.1 — Entrega 1.
- Dicionário: `lab-etl-varejo/lab-etl-varejo/docs/DICIONARIO_DE_DADOS.md`.
- Medição reproduzível: `lab-etl-varejo/lab-etl-varejo/etl/diagnostico_chaves.py`.
- Resultados completos: `lab-etl-varejo/lab-etl-varejo/saida/diagnostico_chaves.json`.
- Execução: na pasta do laboratório, `docker compose exec -T etl python diagnostico_chaves.py`.

*Versão parcial: a questão (a) está respondida; os campos de identificação da equipe e as questões (b) a (e) serão completados antes da geração do PDF final, respeitando o limite de seis páginas.*
