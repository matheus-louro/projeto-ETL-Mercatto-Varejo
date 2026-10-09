# Relatório de Diagnóstico — Mercatto Varejo

**Mineração de Dados · IFMT · Entrega 1**  
**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi  
**Ambiente:** Docker, escala 1,0, semente 20262

## 1. Objetivo e método

Diagnosticar as fontes MySQL legado, PostgreSQL do e-commerce, CSV do SAC e NDJSON de avaliações antes da integração. As medições abrangem as bases completas, sem alteração das origens, e complementam o perfilador fornecido. O objetivo do projeto é prever a recompra entre 01/07/2025 e 28/09/2025 usando o comportamento até 30/06/2025.

## 2. Questão (a) — Chaves de junção e cobertura

**Cobertura = 100 × registros com correspondência / registros examinados.** Cada registro é contado uma vez, mesmo quando sua chave encontra várias ocorrências. Ausências e duplicatas integram o denominador; valores vazios não são pareados. CPF e telefone foram comparados somente por dígitos; e-mail, em minúsculas e sem espaços externos; nomes, sem acentos, em maiúsculas e com espaços uniformizados.

### 2.1. Clientes entre os sistemas

| Candidato | Valores distintos compartilhados | Legado: cobertos / 47.250 | E-commerce: cobertos / 85.000 |
|---|---:|---:|---:|
| `CPF` ↔ `tax_id` | 12.605 | 13.048 (27,61%) | 12.606 (14,83%) |
| `NOME` ↔ `full_name` | 22.869 | 28.204 (59,69%) | 31.360 (36,89%) |
| `EMAIL` ↔ `email` | 0 | 0 (0,00%) | 0 (0,00%) |
| `TELEFONE` ↔ `phone` | 0 | 0 (0,00%) | 0 (0,00%) |

O **CPF é o principal candidato**, mas não garante identidade nem unicidade: 1.427 valores se repetem no legado e 3 no e-commerce; somente 12.161 dos 12.605 CPFs compartilhados são únicos em ambos. Entre os compartilhados, 1.135 (9,00%) têm dígito verificador inválido; excluí-los eliminaria correspondências observáveis. O nome apresenta maior cobertura, porém há 6.758 nomes repetidos no legado e 15.477 no e-commerce, exigindo critérios adicionais para evitar unir pessoas distintas. E-mail e telefone não ligam os cadastros nesta base. Os IDs internos dos dois sistemas também não comprovam identidade entre fontes.

### 2.2. Arquivos para pedidos, clientes e produtos

| Candidato e destino | Cobertos / examinados | Cobertura |
|---|---:|---:|
| SAC: `(origem_sistema, id_pedido_origem)` → pedido na origem indicada | 96.140 / 96.140 | 100,00% |
| SAC: `cpf_cliente` → qualquer cadastro | 90.155 / 96.140 | 93,77% |
| SAC: `cpf_cliente` → cadastro da origem indicada | 88.535 / 96.140 | 92,09% |
| JSON: `order.ref` → pedido da origem indicada | 160.000 / 160.000 | 100,00% |
| JSON: `product.sku` → produto da origem indicada | 160.000 / 160.000 | 100,00% |

A chave de pedido deve incluir a origem, pois IDs podem coincidir entre os bancos. No SAC, `LEGADO` e `ECOM` direcionam a busca a `ID_PEDIDO` e `order_id`. No JSON, `LEG-<id>` referencia IDs do legado, `ECOM-<id>` referencia pedidos do e-commerce e `SKU-<n>` corresponde a `shop.product.sku`. São 40.016 avaliações do legado e 119.984 do e-commerce, com cobertura de 100% para pedidos e produtos em cada grupo.

A ligação do SAC por pedido cobre todas as linhas, inclusive as 5.985 (6,23%) sem CPF em nenhum cadastro. Nas avaliações, a existência de pedido e produto foi verificada separadamente; não comprova que o produto pertence ao pedido. `protocolo` e `review_id` identificam registros locais, sem contraparte direta nos bancos.

### 2.3. Relações internas dos bancos

| Relação e campo da chave | Legado: cobertos / examinados | E-commerce: cobertos / examinados |
|---|---:|---:|
| Pedido → cliente: `ID_CLIENTE` / `customer_id` | 130.000 / 130.000 (100%) | 280.000 / 280.000 (100%) |
| Item → pedido: `ID_PEDIDO` / `order_id` | 391.218 / 397.086 (98,52%) | 980.658 / 995.367 (98,52%) |
| Item → produto: `ID_PRODUTO` / `product_id` | 397.086 / 397.086 (100%) | 995.367 / 995.367 (100%) |

Há 5.868 itens sem pedido no legado e 14.709 no e-commerce (1,48% em cada origem). IDs de produto de sistemas diferentes não estabelecem equivalência comercial.

## 3. Questão (b) — Heterogeneidade semântica

Foram identificados três casos em que campos aparentemente equivalentes representam conceitos diferentes. Variações de idioma, grafia ou formato, isoladamente, não constituem divergência semântica.

### 3.1. Cancelamento e recusa de pagamento

Segundo o esqueleto de conformação fornecido, `CANCELADO` no legado agrega cancelamento pelo cliente e recusa de pagamento; o e-commerce distingue `canceled` de `payment_declined`. As distribuições confirmam a diferença de abrangência:

| Sistema e status | Pedidos / total da origem | Percentual |
|---|---:|---:|
| Legado: `CANCELADO` | 15.774 / 130.000 | 12,13% |
| E-commerce: `canceled` | 22.413 / 280.000 | 8,00% |
| E-commerce: `payment_declined` | 13.990 / 280.000 | 5,00% |

A soma dos dois estados no e-commerce é 36.403 pedidos (13,00%). Comparar apenas `canceled` com `CANCELADO` excluiria as recusas da segunda fonte. Agrupar os estados permite comparação mais ampla, mas perde a distinção disponível no e-commerce. O motivo específico não pode ser recuperado no legado.

### 3.2. Composição do valor do pedido

`VALOR_TOTAL` do legado inclui frete; `total_amount` do e-commerce corresponde ao valor líquido dos itens. Essa diferença foi confirmada nos 130.000 pedidos do legado e nos 280.000 do e-commerce (100% de cada origem), com resíduo máximo de R$ 0,00 nas respectivas fórmulas. Comparar ou somar esses campos diretamente misturaria medidas distintas. A prova e os critérios de reconciliação estão na questão (c).

### 3.3. Abrangência das categorias de produto

O legado tem 27 rótulos distintos, considerando caixa e acentos, para 3.000 produtos; o e-commerce tem 21 nós de categoria (8 raízes e 13 filhos), para 12.000 produtos. “Categoria” pode representar um ramo, uma categoria específica ou uma combinação de ramos:

- `informatica e games`: 112 produtos (3,73% do legado), reunindo dois ramos separados no e-commerce.
- `TV E SOM`: 111 (3,70%), reunindo `Televisores` e `Áudio`, que classificam 793 e 805 produtos no e-commerce.
- `DIVERSOS`, `OUTROS` e vazio: 340 (11,33%), sem ramo comercial identificável.

Padronizar grafias não resolve essas diferenças de significado. Atribuir uma categoria combinada a um único ramo descartaria parte da classificação; separá-la exige informação adicional por produto. Os 27 rótulos, portanto, não equivalem a 27 categorias comerciais.

## 4. Questão (c) — Reconciliação financeira

**Os campos não medem a mesma coisa:** `VALOR_TOTAL` inclui frete, enquanto `total_amount` o exclui. Para verificar, os itens foram agregados por ID de pedido antes da junção ao cabeçalho, evitando repetir totais e fretes. Foram examinados todos os pedidos, independentemente do status; itens órfãos não entram na soma de nenhum pedido existente.

Para cada pedido $p$, definiu-se o valor líquido dos itens:

$$L_p = \sum_{i \in I_p} (q_i u_i - d_i^*)$$

Em que $I_p$ são os itens do pedido, $q_i$ é a quantidade, $u_i$ o preço unitário praticado e $d_i^*$ o desconto da linha. Foram usados `QTD`, `VL_UNITARIO` e `VL_DESCONTO` no legado; `quantity`, `unit_price` e `discount` no e-commerce.

No legado, o sentinela `VL_DESCONTO = -1` contribuiu como zero no teste. Essa hipótese é compatível com os totais registrados, mas não recupera o desconto real ausente. Há 4.056 itens com esse sentinela em 4.003 pedidos (3,08% dos 130.000); subtrair literalmente `-1` acrescentaria R$ 1,00 por item e faria esses pedidos falharem na reconciliação. Os fretes foram usados com o sinal original, inclusive quando negativos.

| Hipótese para o total registrado | Legado: 130.000 pedidos | E-commerce: 280.000 pedidos |
|---|---:|---:|
| $L_p + \text{frete}_p$ | 130.000 (100,00%) | 94 (0,03%) |
| $L_p$, sem frete | 33 (0,03%) | 280.000 (100,00%) |

A tolerância foi R$ 0,02 por pedido. Nas fórmulas confirmadas, o maior resíduo absoluto foi **R$ 0,00**. As 33 e 94 coincidências com a hipótese alternativa decorrem de fretes cuja magnitude está dentro da tolerância. A reconciliação agregada também confirma o resultado:

| Medida agregada (R$) | Legado | E-commerce |
|---|---:|---:|
| Soma dos totais registrados | 281.084.957,13 | 734.859.099,95 |
| Soma dos itens líquidos | 275.324.024,56 | 734.859.099,95 |
| Soma dos fretes | 5.760.932,57 | 10.991.760,38 |

No legado, **281.084.957,13 = 275.324.024,56 + 5.760.932,57**. No e-commerce, a soma dos totais já é igual à soma dos itens líquidos; incluir frete exigiria acrescentar R$ 10.991.760,38. Portanto, uma medida comparável de total com frete deve manter `VALOR_TOTAL` no legado e adicionar `freight_amount` a `total_amount` no e-commerce, preservando a origem das medidas.

## 5. Questão (d) — Anomalias e limites do diagnóstico

O diagnóstico das fontes completas permitiu quantificar anomalias locais estruturais e semânticas que afetam a qualidade dos dados antes da integração:

* **Valores sentinela:** No legado, 1.025 dos 130.000 pedidos (0,79%) registram a data de entrega como `1900-01-01`. Esse artifício para contornar a ausência de data realiza um deslocamento nas médias cronológicas.
* **Inconsistências cronológicas e financeiras:** Entregas registradas antes do próprio pedido ocorrem em 775 pedidos do legado (0,60%) e 1.683 do e-commerce (0,60%). Além disso, há valores de frete negativos em 362 pedidos do legado (0,28%) e 812 do e-commerce (0,29%). Estes representam defeitos sistêmicos ou cancelamentos compensatórios que exigem investigação.
* **Referências órfãs:** A integridade referencial está quebrada em ambas as origens. Há 5.868 itens sem pedido correspondente no legado (1,48% de 397.086 itens) e 14.709 no e-commerce (1,48% de 995.367). 
* **Qualidade e tipagem em arquivos:** O SAC (96.140 chamados) tem 2.830 notas de satisfação fora do domínio esperado (1 a 5) e 1.377 registros contêm quebras de linha internas, exigindo tratamento de conversão e formatação. No JSON (160.000 avaliações), 4.831 registros (3,02%) omitem o campo `rating`, e dentre os presentes, 16.108 (10,38%) são formatados como texto (`string`) em vez de inteiro.

**Limites do diagnóstico e problemas revelados apenas na integração:**
As anomalias supracitadas foram detectadas por consultas e perfilamentos locais independentes. No entanto, os defeitos semânticos mais graves dependem do resultado do cruzamento das bases e da aplicação de regras de negócio integradas.
A divergência principal é a composição do valor dos pedidos: conforme provado na questão (c), o legado embute o frete no total, mas o e-commerce o isola. Um diagnóstico unifonte não detecta problemas nesses valores, pois eles são válidos localmente. Integrá-los sem uma regra de equiparação causaria viés analítico ao superestimar a receita de clientes antigos. Da mesma forma, o tratamento de identidades duplicadas e CPFs incorretos (presentes igualmente nas duas bases) dita a sobrevivência do registro. Se as regras de integração aglutinarem equivocadamente pessoas distintas, o modelo preditivo será treinado com históricos contaminados e hiperinflacionados.

## 6. Questão (e) — Grão das tabelas-fato

O modelo dimensional estabelece as seguintes unidades de análise para preservar a rastreabilidade e evitar o produto cartesiano ao agregar as métricas:

* Uma linha de `dw.fato_pedido` representa um único pedido comercializado em qualquer um dos sistemas de origem.
* Uma linha de `dw.fato_item_pedido` representa um produto unitário faturado dentro de um pedido específico.
* Uma linha de `dw.fato_atendimento` representa um registro de atendimento (chamado) aberto no SAC.
* Uma linha de `dw.fato_avaliacao` representa uma avaliação de produto enviada por um cliente ao marketplace.

A chave primária local dos pedidos (`ID_PEDIDO` no legado e `order_id` no e-commerce) é insuficiente para garantir a unicidade no ambiente integrado. Os sistemas geradores operam de forma isolada e emitem sequências numéricas idênticas. Devido a essa colisão inevitável de identificadores, a origem compõe a identificação obrigatória no Data Warehouse (através da chave composta por `id_origem` e `sistema_origem`), assegurando que um pedido oriundo do legado e um do e-commerce com o mesmo número sejam corretamente apartados e reconhecidos como eventos distintos.

## Referências e reprodução

Projeto Prático ETL Mercatto, seção 3.1; Dicionário de Dados e esqueleto de transformação do laboratório. Medições: `diagnostico_chaves.py` e `diagnostico_semantica.py`, na pasta `etl`; resultados em arquivos JSON homônimos, na pasta `saida`.
