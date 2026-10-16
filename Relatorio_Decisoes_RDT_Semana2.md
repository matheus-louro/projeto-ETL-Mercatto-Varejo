# Relatório de Decisões de Transformação (RDT) — Mercatto Varejo

**Mineração de Dados · IFMT · Entrega 2 (Semana 2)**  
**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi  
**Ambiente:** Docker, escala 1.0, semente determinística 20262  
**Versão do Pipeline:** 0.2.0 (Extração e Conformação)

---

# Parte I — Fase de Extração (stg)

## 1. Contexto Arquitetural e Princípios de Ingestão

A fase de extração estabelece a transição entre o perfilamento observacional e a engenharia de dados propriamente dita. Conforme o referencial teórico da disciplina (*ETL como Preparação de Dados na Mineração de Dados*), a camada de *staging* (`stg`) opera como uma área de pouso transitória e inviolável, regida por três princípios:

* **1. Espelhamento Fidedigno:** Os nomes das colunas, tipos de dados e granularidades refletem com exatidão as origens transacionais. Nenhuma coluna é renomeada ou limpa precocemente na extração.
* **2. Imutabilidade Semântica:** Nenhum valor nulo é preenchido, nenhum valor sentinela (como `1900-01-01` ou `-1`) é mascarado e nenhuma deduplicação ou unificação é executada nesta camada.
* **3. Linhagem e Rastreabilidade Técnica:** Todo registro inserido recebe exclusivamente dois metadados operacionais de auditoria:
  * `_fonte`: Identificador textual do sistema emissor (`legado`, `ecom`, `sac`, `mkt`).
  * `_extraido_em`: Timestamp em UTC do instante exato de execução da leitura.

---

## 2. Ficha RDT-01 — Estratégia de Carga para a Staging (Full Load vs. Incremental)

### 2.1. A Decisão
Adoção do modelo de **Carga Completa (*Full Load*)** por substituição de partição/tabela (`if_exists="replace" / truncate + append`) com paginação em lotes de 50.000 registros (`chunksize`), descartando o modelo de carga incremental (*Delta Load*).

* **Script associado:** `01_extracao.py` (funções `extrai_mysql`, `extrai_postgres`, `extrai_sac`, `extrai_avaliacoes`).

### 2.2. O que o Dado Mostrava (Evidência Quantificada)
A auditoria das quatro fontes revelou limitações intransponíveis para a implementação de um mecanismo confiável de extração incremental:
1. **Ausência de Timestamps de Atualização (`updated_at`):**
   * No MySQL Legado (`loja_legado`), as tabelas `CLIENTES` (47.250 linhas), `PRODUTOS` (3.000 linhas) e `ITENS_PEDIDO` (397.086 linhas) não possuem colunas de data. A tabela `PEDIDOS` (130.000 linhas) dispõe apenas de `DT_PEDIDO` e `DT_ENTREGA`, sem controle de modificação ou log binário.
   * No PostgreSQL E-commerce (`shop`), a tabela `order_item` (995.367 linhas) é gravada sem qualquer atributo temporal.
2. **Mutabilidade Tardia de Pedidos:** Pedidos sofrem alteração de status semanas após a compra (ex.: de `EM TRANSITO` para `ENTREGUE` ou `CANCELADO`, e no e-commerce para `canceled` ou `payment_declined`). Uma carga incremental filtrando apenas compras recentes deixaria de capturar atualizações de status de pedidos antigos, congelando estados defasados no DW.
3. **Arquivos Estáticos Desprovidos de Versionamento:** Os arquivos `atendimentos_sac.csv` (96.140 linhas) e `avaliacoes_marketplace.json` (160.000 objetos) são extrações monolíticas em lote único, sem mecanismos de ponteiro incremental (*offset*).
4. **Volume Consolidado Plenamente Tratável:** A soma das quatro fontes totaliza **2.205.864 registros** (~150 MB brutos), volume cujo custo computacional não justifica o risco analítico de inconsistências em cargas parciais.

### 2.3. Alternativas Consideradas
* **Alternativa 1 — Carga Incremental por Data de Criação (*Watermark* em `DT_PEDIDO` / `placed_at`):**
  * *Por que foi descartada:* Ignoraria mutações de status ocorridas após a data do pedido e é inviável para itens e produtos que não possuem campo de data.
* **Alternativa 2 — Carga Completa (*Full Load*) Particionada em Lotes de Memória (`chunksize = 50.000`):**
  * *Decisão:* **Adotada**. Recarrega a staging integralmente a cada ciclo de execução, processando em blocos paginados para respeitar os limites de memória RAM do contêiner Docker.

### 2.4. Justificativa e Racionalidade Técnica
1. **Garantia de Integridade e Simetria:** Assegura que o estado da staging reflita a realidade exata das fontes a cada rodada, eliminando registros órfãos ou status defasados no DW.
2. **Reprodutibilidade Determinística:** Atende estritamente ao critério de avaliação nº 5 do edital, garantindo que o comando de reconstrução a frio (`docker compose down -v && ...`) funcione perfeitamente.
3. **Eficiência Viável:** O tempo de carga dos 2,2 milhões de registros com inserção em blocos (`method='multi'`) é inferior a 3 minutos.

### 2.5. O que se Perde e Trade-offs
* **Redundância Computacional:** A cada execução, 100% dos registros antigos são relidos e regravados, gerando tráfego de rede e E/S que seriam evitados em arquiteturas para bilhões de linhas.
* **Histórico Efêmero na Staging:** A staging não armazena fotografias temporais intermediárias (o rastreamento histórico de mudanças é delegado exclusivamente às dimensões do DW).

### 2.6. Registros Afetados (100% da Base Integrada)

| Fonte de Origem | Tabela / Arquivo | Destino na Staging (`stg`) | Registros Extraídos | % da Base Total |
| :--- | :--- | :--- | ---: | ---: |
| **MySQL Legado** | `CLIENTES` | `stg.legado_clientes` | 47.250 | 2,14% |
| **MySQL Legado** | `PRODUTOS` | `stg.legado_produtos` | 3.000 | 0,14% |
| **MySQL Legado** | `PEDIDOS` | `stg.legado_pedidos` | 130.000 | 5,89% |
| **MySQL Legado** | `ITENS_PEDIDO` | `stg.legado_itens_pedido` | 397.086 | 18,00% |
| **PG E-commerce** | `shop.customer` | `stg.ecom_customer` | 85.000 | 3,85% |
| **PG E-commerce** | `shop.product` | `stg.ecom_product` | 12.000 | 0,54% |
| **PG E-commerce** | `shop.orders` | `stg.ecom_orders` | 280.000 | 12,69% |
| **PG E-commerce** | `shop.order_item` | `stg.ecom_order_item` | 995.367 | 45,12% |
| **PG E-commerce** | `shop.category` | `stg.ecom_category` | 21 | < 0,01% |
| **Arquivo CSV** | `atendimentos_sac.csv` | `stg.sac_atendimentos` | 96.140 | 4,36% |
| **Arquivo NDJSON** | `avaliacoes_marketplace.json` | `stg.mkt_avaliacoes` | 160.000 | 7,25% |
| **Total Consolidado** | — | — | **2.205.864** | **100,00%** |

### 2.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
1. **Asserções de Contagem e Não-Perda de Linhas:** 9 asserções `qa.igual("linhas <origem> vs stg")` validando a contagem de cada tabela contra as fontes relacionais.
2. **Asserção de Integridade do SAC:** `qa.sem_nulos("protocolo do SAC", stg_sac["protocolo"])`, confirmando que quebras de linha no CSV não corromperam registros.
3. **Asserção de Unicidade no Marketplace:** `qa.unico("review_id marketplace", stg_mkt["review_id"])`, garantindo que nenhum objeto NDJSON foi duplicado na ingestão.

---

# Parte II — Fase de Transformação e Conformação

## 3. Decisão 1 — Identidade do Cliente e Deduplicação Interna

A resolução da identidade do cliente constitui a pedra angular do repositório analítico. A pergunta central de negócio (*"o cliente voltará a comprar nos próximos 90 dias?"*) exige que o grão da dimensão de clientes seja rigorosamente unívoco: não se pode misturar pessoas distintas (falso positivo) nem fragmentar o histórico de transações de uma mesma pessoa em cadastros múltiplos (falso negativo).

No código de transformação (`02_transformacao.py` — função `unifica_clientes`), esta decisão desdobra-se em duas fichas metodológicas complementares:
* **Ficha RDT-02:** Pareamento e unificação inter-sistemas (Legado ↔ E-commerce).
* **Ficha RDT-03:** Deduplicação intra-sistema no Legado e rastreabilidade por mapeamento De-Para.

---

### 3.1. Ficha RDT-02 — Unificação de Identidade entre Sistemas (Legado ↔ E-commerce)

#### 3.1.1. A Decisão
Adoção do pareamento determinístico estritamente por **CPF normalizado (11 dígitos numéricos limpos)**, unificando os clientes independentemente de o dígito verificador ser matematicamente válido ou inválido perante o algoritmo da Receita Federal. Rejeita-se o pareamento aproximado (*fuzzy*) por Nome, Cidade e UF para os clientes sem documento (~8% em cada origem), mantendo-os apartados no DW como entidades distintas.

* **Script associado:** `02_transformacao.py` (função `unifica_clientes`).

#### 3.1.2. O que o Dado Mostrava (Evidência Quantificada)
1. **Interseção Real de CPFs:** No cruzamento entre as 41.400 pessoas com CPF no legado e as 78.142 no e-commerce, encontram-se exatamente **12.605 CPFs idênticos na interseção**, representando **84,9%** dos aproximadamente 14.850 clientes verdadeiramente sobrepostos na semente 20262.
2. **A Armadilha dos Dígitos Inválidos:** Entre os 12.605 CPFs compartilhados, exatamente **1.135 registros (9,00%) possuem dígitos verificadores inválidos** em ambos os sistemas. O erro de digitação cometido na loja física foi propagado de forma idêntica para o cadastro digital.
3. **Risco Crítico de Homonímia:** Embora existam 22.869 nomes compartilhados entre as bases, há 6.758 nomes repetidos internamente no legado e 15.477 no e-commerce. Parear por nome causaria a falsa fusão de homônimos (pessoas distintas com o mesmo nome).

#### 3.1.3. Alternativas Consideradas
* **Alternativa 1 — Filtragem e Descarte de CPFs com Dígito Inválido:**
  * *Por que foi descartada:* Descartaria sumariamente 1.135 clientes legítimos sobrepostos (9,00% da interseção). Validade algorítmica não é sinônimo de utilidade identificadora: mesmo matematicamente imperfeito, o número permaneceu estável e único para a mesma pessoa física em ambas as plataformas.
* **Alternativa 2 — Pareamento Aproximado (*Fuzzy Matching*) por Nome + Cidade + UF para Ausências:**
  * *Por que foi descartada:* Gera alto risco de **falsos positivos**. Fundir duas pessoas diferentes agrega artificialmente seus históricos de compra, inflando recência, frequência e valor monetário, contaminando a base de treinamento da recompra.
* **Alternativa 3 — Pareamento Determinístico por CPF Normalizado (Válidos e Inválidos) com Isolamento das Ausências:**
  * *Decisão:* **Adotada**. Unifica exclusivamente por CPF limpo de 11 dígitos. Registros sem documento são mantidos como entidades separadas (`origem_unificacao IN ('LEGADO', 'ECOM')`).

#### 3.1.4. Justificativa e Racionalidade Técnica
Para a mineração preditiva de recompra, o erro de falso positivo (fundir duas pessoas reais em uma só) é epistemicamente desastroso, pois contamina o rótulo do cliente com compras alheias. Já o erro de falso negativo (manter a mesma pessoa em dois IDs se ela comprou sem CPF) apenas gera dois perfis analíticos independentes sem corromper compras reais.

#### 3.1.5. O que se Perde e Trade-offs
* **Perda de sobreposições sem documento:** Perdem-se os ~15,1% de clientes verdadeiramente sobrepostos (~2.245 indivíduos) que não informaram o CPF em pelo menos uma das lojas.
* **Persistência de cadastros imperfeitos:** Admitem-se na dimensão identificadores que falhariam em validações formais de crédito ou faturamento fiscal.

#### 3.1.6. Registros Afetados na Dimensão de Clientes (`dw.dim_cliente`)

| Origem / Categoria de Unificação | Volume de Clientes | % em `dw.dim_cliente` | Regra de Pareamento |
| :--- | ---: | ---: | :--- |
| **AMBOS (Sobreposição Confirmada)** | **12.605** | **10,66%** | `CPF_EXATO` (válidos e inválidos) |
| **LEGADO (Exclusivos ou sem CPF)** | **33.218** | **28,10%** | `APENAS_LEGADO` / `SEM_CPF_LEGADO` |
| **ECOM (Exclusivos ou sem CPF)** | **72.392** | **61,24%** | `APENAS_ECOM` / `SEM_CPF_ECOM` |
| **Total Conformado em `dw.dim_cliente`** | **118.215** | **100,00%** | Grão dimensional consolidado |

#### 3.1.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("clientes unificados em AMBOS", 12605)`: confirmação da interseção exata de CPFs.
* `qa.unico("cpf_normalizado sem duplicatas entre validos")`: garantia de ausência de duplicação entre CPFs válidos.
* `qa.dominio("origem_unificacao em {LEGADO,ECOM,AMBOS}")`: estrita aderência ao vocabulário controlado.
* `qa.cardinalidade_preservada("cardinalidade dim_cliente")`: confirmação de que a unificação reduziu cardinalidade sem multiplicar registros.

---

### 3.2. Ficha RDT-03 — Tratamento de Duplicatas Internas no Sistema Legado

#### 3.2.1. A Decisão
Deduplicação intra-sistema no Legado agrupando pelo CPF numérico (`so_digitos`), elegendo o registro de menor `ID_CLIENTE` como **canônico** e gerando uma tabela de mapeamento de procedência (`stg.map_cliente_legado`) para preservar a integridade referencial dos pedidos faturados.

* **Script associado:** `02_transformacao.py` (função `unifica_clientes`).

#### 3.2.2. O que o Dado Mostrava (Evidência Quantificada)
Na tabela `stg.legado_clientes` (47.250 linhas), existem apenas 41.400 CPFs distintos. Há **2.854 linhas envolvidas em duplicações cadastrais internas**:
* **2% de duplicatas exatas:** Mesmo CPF, mesmo nome e mesmos atributos cadastrais repetidos.
* **3% de duplicatas aproximadas:** Mesmo CPF numérico, mas com grafias divergentes no nome (espaços duplos, falta de acentos ou máscaras parciais).

#### 3.2.3. Alternativas Consideradas
* **Alternativa 1 — Exclusão Simples dos Registros Duplicados Excedentes:**
  * *Por que foi descartada:* No Legado, centenas de pedidos históricos apontam diretamente para o `ID_CLIENTE` da linha duplicada. Excluir o ID redundante geraria pedidos órfãos na tabela-fato de pedidos do DW.
* **Alternativa 2 — Eleição de Registro Canônico com Tabela De-Para de Chaves:**
  * *Decisão:* **Adotada**. O registro de menor ID torna-se a entidade principal em `dw.dim_cliente`, e a tabela `stg.map_cliente_legado(id_legado_orig, cliente_sk)` mapeia todas as variações para o mesmo `cliente_sk`.

#### 3.2.4. Justificativa e Racionalidade Técnica
Preserva a regra de ouro da modelagem dimensional: uma única linha por entidade real na dimensão, mantendo ao mesmo tempo 100% de rastreabilidade referencial para os 130.000 pedidos legados.

#### 3.2.5. O que se Perde e Trade-offs
* **Perda de variações secundárias de endereço:** Se um cliente duplicado alterou sua cidade ou telefone no segundo cadastro, apenas os atributos do registro canônico eleito sobrevivem na dimensão.

#### 3.2.6. Registros Afetados
* **1.427 registros redundantes colapsados** no sistema Legado (redução de 47.250 linhas brutas para 45.823 clientes únicos legados).
* **47.250 pares mapeados** na tabela auxiliar `stg.map_cliente_legado`.

---

## 4. Decisão 2 — Conformação Hierárquica de Status de Pedidos (Ficha RDT-04)

### 4.1. A Decisão
Adoção de um modelo dimensional hierárquico em dois níveis na dimensão `dw.dim_status`:
1. **Nível 1 (`status_conformado`):** Macro-estado operacional padronizado (`ENTREGUE`, `EM_TRANSITO`, `SEPARACAO`, `CANCELADO`), unificando semanticamente pedidos equivalentes entre as fontes.
2. **Nível 2 (`motivo_cancelamento`):** Sub-classificação preenchida exclusivamente quando a fonte discrimina o motivo (`SOLICITACAO_CLIENTE` para desistências e `RECUSA_PAGAMENTO` para bloqueios de crédito/antifraude no e-commerce), permanecendo `NULL` para o legado.

* **Script associado:** `02_transformacao.py` (função `conforma_status`).

---

### 4.2. O que o Dado Mostrava (Evidência Quantificada)
A distribuição dos 410.000 pedidos das duas origens evidencia que o sistema legado aglutina duas ocorrências comerciais que a plataforma digital mantém estritamente segregadas:

| Origem | Status Original | Ocorrências | % na Origem | Equivalente no DW (`status_conformado`) | Detalhe (`motivo_cancelamento`) |
| :--- | :--- | ---: | ---: | :--- | :--- |
| **Legado** | `ENTREGUE` | 101.192 | 77,84% | `ENTREGUE` | `NULL` |
| **Legado** | `CANCELADO` | 15.774 | 12,13% | `CANCELADO` | `NULL` |
| **Legado** | `EM TRANSITO` | 7.798 | 6,00% | `EM_TRANSITO` | `NULL` |
| **Legado** | `SEPARACAO` | 5.236 | 4,03% | `SEPARACAO` | `NULL` |
| **E-commerce** | `delivered` | 207.204 | 74,00% | `ENTREGUE` | `NULL` |
| **E-commerce** | `canceled` | 22.413 | 8,00% | `CANCELADO` | `SOLICITACAO_CLIENTE` |
| **E-commerce** | `payment_declined` | 13.990 | 5,00% | `CANCELADO` | `RECUSA_PAGAMENTO` |
| **E-commerce** | `shipped` | 22.375 | 7,99% | `EM_TRANSITO` | `NULL` |
| **E-commerce** | `processing` | 14.018 | 5,01% | `SEPARACAO` | `NULL` |

Nota-se que a soma de `canceled` (8,00%) e `payment_declined` (5,00%) no e-commerce perfaz exatamente 13,00% dos pedidos, proporção muito próxima aos 12,13% de cancelamentos agregados do legado.

---

### 4.3. Alternativas Consideradas

* **Alternativa 1 — Achatamento Unidimensional (Mapear `payment_declined` e `canceled` diretamente para `CANCELADO`):**
  * *Por que foi descartada:* Destrói irreversivelmente a riqueza analítica do e-commerce. Para modelagem preditiva de retenção (recompra), um consumidor com pagamento recusado frequentemente tenta recomprar com outro meio ou cartão, enquanto o cancelamento voluntário sinaliza desistência comercial ou insatisfação com prazos.
* **Alternativa 2 — Bifurcação Horizontal de Status Primários (`CANCELADO_CLIENTE` e `CANCELADO_PAGAMENTO`):**
  * *Por que foi descartada:* Como o legado (15.774 pedidos) não possui a informação do motivo, esses pedidos ficariam eternamente como uma terceira categoria assimétrica (`CANCELADO_NAO_INFORMADO`), quebrando comparações diretas de taxas de conversão e cancelamento global entre os canais físico e digital.
* **Alternativa 3 — Modelo Hierárquico em Dois Níveis (`status_conformado` + `motivo_cancelamento`):**
  * *Decisão:* **Adotada**. Harmoniza o macro-status para análises transversais globais e preserva a especificidade em atributo secundário da dimensão para os algoritmos de Machine Learning.

---

### 4.4. Justificativa e Racionalidade Técnica
Permite consultas analíticas agregadas limpas (ex.: `WHERE status_conformado = 'CANCELADO'`) sem perder o detalhamento transacional de atrito de pagamento para o e-commerce. Respeita a realidade histórica dos dados sem inventar ou imputar dados falsos no legado.

---

### 4.5. O que se Perde e Trade-offs
Assume-se a assimetria informativa: o analista que filtrar por `motivo_cancelamento` precisará estar ciente de que pedidos originários da loja física não possuem discriminação do evento de cancelamento (o que reflete com fidelidade a limitação da tecnologia legada).

---

### 4.6. Registros Afetados
* **52.177 pedidos cancelados no total** (15.774 do legado e 36.403 do e-commerce).
* **410.000 pedidos consolidados** passam a apontar para as 9 linhas conformadas de `dw.dim_status`.

---

### 4.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("total de linhas dim_status", 9)`: garantia de que todos os estados de origem foram mapeados.
* `qa.unico("status_origem e sistema unicos")`: unicidade da chave composta na dimensão de status.
* `qa.dominio("macro-status permitidos", {"ENTREGUE", "CANCELADO", "EM_TRANSITO", "SEPARACAO"})`: aderência ao vocabulário canônico.

---

## 5. Decisão 3 — Semântica dos Valores Monetários e Sentinelas Financeiros

A reconciliação financeira entre cabeçalhos de pedidos e linhas de itens representa a prova de fogo de qualquer pipeline de engenharia de dados. Conforme exigido na Semana 3 do edital do projeto, a soma de faturamento no Data Warehouse deve ficar dentro de 0,1% do total auditado na origem.

No código de transformação (`02_transformacao.py` — função `conforma_valores`), esta decisão abrange duas fichas metodológicas:
* **Ficha RDT-05:** Equalização semântica das grandezas de `VALOR_TOTAL` e `total_amount` e desacoplamento em 4 medidas canônicas.
* **Ficha RDT-06:** Normalização do sentinela de desconto `-1` e tratamento contábil de fretes negativos.

---

### 5.1. Ficha RDT-05 — Definição de `VALOR_TOTAL` e `total_amount` (Reconciliação Financeira)

#### 5.1.1. A Decisão
Adoção de uma estrutura analítica de **quatro medidas financeiras unificadas e explicitamente calculadas** na tabela-fato de pedidos (`dw.fato_pedido` e `stg.pedidos_conformados`):
1. `valor_mercadoria`: Valor monetário líquido das mercadorias ($\sum \text{quantidade} \times \text{preço unitário} - \text{desconto}$), **estritamente sem frete**.
2. `valor_frete`: Custo logístico de frete da entrega.
3. `valor_desconto`: Total de abatimentos comerciais aplicados aos itens.
4. `valor_total`: Medida contábil consolidada do pedido: $\text{valor\_mercadoria} + \text{valor\_frete}$.

* **Script associado:** `02_transformacao.py` (função `conforma_valores`).

#### 5.1.2. O que o Dado Mostrava (Evidência Quantificada)
A reconciliação financeira contra a soma dos 1.392.453 itens comprova que os campos originais de total medem grandezas econômicas distintas:
* **Legado (130.000 pedidos):** `VALOR_TOTAL` registra **R$ 281.084.957,13**, exatamente igual à soma dos itens líquidos (**R$ 275.324.024,56**) somada ao frete (**R$ 5.760.932,57**). 130.000 de 130.000 pedidos (100,00%) embutem o frete no total registrado.
* **E-commerce (280.000 pedidos):** `total_amount` registra **R$ 734.859.099,95**, exatamente igual à soma dos itens líquidos (**R$ 734.859.099,95**), sem frete. O frete total (**R$ 10.991.760,38**) estava segregado em `freight_amount`. 280.000 de 280.000 pedidos (100,00%) excluem o frete do total registrado.

O resíduo matemático nas duas fórmulas após o cálculo foi de **R$ 0,00** (tolerância de R$ 0,02 respeitada em 100% dos 410.000 pedidos).

#### 5.1.3. Alternativas Consideradas
* **Alternativa 1 — Ingestão Direta dos Campos Brutos (`VALOR_TOTAL` e `total_amount`):**
  * *Por que foi descartada:* Produziria um erro financeiro silencioso grave: superestimaria a receita de clientes antigos da loja física (com frete embutido) e subestimaria a receita de clientes da plataforma digital (com frete omitido), enviesando severamente variáveis preditivas de valor monetário (LTV).
* **Alternativa 2 — Padronizar o Total sem Frete (Subtrair o frete do legado):**
  * *Por que foi descartada:* Ignora o impacto do custo logístico na decisão de compra e no desembolso real do consumidor, além de impossibilitar a conciliação bancária da receita bruta da Mercatto.
* **Alternativa 3 — Decomposição em Quatro Medidas Explícitas e Equalizadas:**
  * *Decisão:* **Adotada**. Isola mercadoria, frete e desconto, gerando uma medida total contábil idêntica em ambos os sistemas.

#### 5.1.4. Justificativa e Racionalidade Técnica
Garante integridade conceitual absoluta: o analista ou modelo de Machine Learning pode escolher consultar estritamente o gasto com produtos (`valor_mercadoria`) ou o faturamento global da compra (`valor_total`), com regras perfeitamente simétricas entre as unidades de negócio.

#### 5.1.5. O que se Perde e Trade-offs
O campo `total_amount` do e-commerce deixa de ser o "total final" no DW, passando a compor `valor_mercadoria`, enquanto `valor_total` passa a incorporar o frete para refletir o custo integral da transação.

#### 5.1.6. Registros Afetados
* **410.000 pedidos** conformados e recalculados (130.000 do legado e 280.000 do e-commerce).
* **1.392.453 itens de pedidos** consolidados e auditados.

#### 5.1.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("reconciliacao valor_mercadoria vs itens", 0)`: zero pedidos com divergência de itens > R$ 0,02.
* `qa.igual("pedidos conformados carregados", 410000)`: 100% dos pedidos reconciliados e carregados.

---

### 5.2. Ficha RDT-06 — Tratamento do Sentinela de Desconto `-1` e Fretes Negativos

#### 5.2.1. A Decisão
1. **Desconto Sentinela:** Aplicação da função `GREATEST("VL_DESCONTO", 0)` nos itens do legado, convertendo o sentinela `-1` em `0.00`.
2. **Fretes Negativos:** Manutenção do sinal algébrico dos fretes negativos na fórmula de composição do valor total, tratando-os como subsídio/crédito logístico concedido no checkout.

* **Script associado:** `02_transformacao.py` (função `conforma_valores`).

#### 5.2.2. O que o Dado Mostrava (Evidência Quantificada)
* **Sentinela `-1`:** No legado, 4.056 itens em 4.003 pedidos (3,08% dos pedidos da origem) registram `VL_DESCONTO = -1`. Se computado literalmente como número, a expressão $Q \times V - (-1)$ adicionaria R$ 1,00 por item, fazendo 4.003 pedidos falharem na reconciliação financeira contra o cabeçalho.
* **Frete Negativo:** Ocorrem valores negativos de frete em 362 pedidos do legado (0,28%) e 812 pedidos do e-commerce (0,29%), totalizando 1.174 pedidos (0,29% do DW). Na contabilidade original do legado, esses fretes negativos já reduziam o valor do pedido registrado em `VALOR_TOTAL`.

#### 5.2.3. Alternativas Consideradas
* **Alternativa 1 — Interpretar `-1` literalmente como acréscimo ou erro de cobrança:**
  * *Por que foi descartada:* Erro contábil evidente. O valor `-1` foi comprovado como convenção de programação (*sentinela*) para campos não aplicáveis.
* **Alternativa 2 — Truncar/Zerar fretes negativos para `0.00`:**
  * *Por que foi descartada:* No legado, o cabeçalho financeiro foi fechado considerando o abatimento desse frete negativo. Zerá-lo geraria resíduo contábil e faria a carga do DW divergir da receita histórica auditada da origem.
* **Alternativa 3 — Normalizar Sentinela para Zero e Preservar a Regra de Fechamento Contábil:**
  * *Decisão:* **Adotada**. Converte `-1` em zero e soma o frete com seu sinal original.

#### 5.2.4. Justificativa e Racionalidade Técnica
Elimina a distorção do sentinela de desconto mantendo conformidade perfeita com os totais de pedidos auditados nas origens.

#### 5.2.5. O que se Perde e Trade-offs
Perde-se o rastro de que o item específico possuía o código `-1` no banco antigo (a fato passa a conter `0.00`).

#### 5.2.6. Registros Afetados
* **4.056 itens de pedido** com sentinela `-1` normalizados no legado.
* **1.174 pedidos** com fretes negativos preservados na contabilidade analítica.

#### 5.2.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("reconciliacao valor_mercadoria vs itens", 0)`: garantia de fechamento exato.

---

## 6. Decisão 4 — Taxonomia de Categorias de Produtos e Resolução de Casos Ambíguos (Ficha RDT-07)

### 6.1. A Decisão
Adoção da árvore taxonômica de dois níveis do e-commerce como padrão oficial do Data Warehouse (`categoria_nivel1` para macro-departamento e `categoria_nivel2` para subcategoria na dimensão `dw.dim_produto`), normalizando as 27 variações de texto livre do legado através de mapeamento De-Para determinístico e preservando obrigatoriamente a evidência histórica na coluna `categoria_origem`.

Tratamento explícito dos casos sem solução taxonômica limpa:
1. **Rótulo Híbrido Multi-Departamento (`'informatica e games'`, 112 produtos):** Mapeado para `categoria_nivel1 = 'Informática'` com `categoria_nivel2 = NULL`, registrando o descarte da especificidade de games.
2. **Rótulo Híbrido Multi-Subcategoria (`'TV E SOM'`, 111 produtos):** Mapeado para `categoria_nivel1 = 'Áudio e TV'` com `categoria_nivel2 = NULL` (já que o conceito engloba conjuntamente as subcategorias `Televisores` e `Áudio`).
3. **Rótulos Genéricos e Vazios (`'DIVERSOS'`, `'OUTROS'`, `''`, 340 produtos):** Mapeados para `categoria_nivel1 = 'Outros'` com `categoria_nivel2 = NULL`, atestando com honestidade que a fonte legada não coletava o atributo comercial.

* **Script associado:** `02_transformacao.py` (função `conforma_categorias`).

---

### 6.2. O que o Dado Mostrava (Evidência Quantificada)
* **E-commerce:** 12.000 produtos estruturados em 21 nós hierárquicos controlados (8 categorias de Nível 1 e 13 de Nível 2).
* **Legado:** 3.000 produtos classificados por digitação livre em 27 rótulos:
  * **2.437 produtos (81,23%):** Conceitos com equivalência semântica direta, fragmentados por grafia, caixa alta, acentos ou hífens (ex.: `ELETRO`, `Eletro-domesticos`, `ELETRODOMÉSTICOS` totalizando 533 produtos).
  * **223 produtos (7,43%):** Rótulos que cruzam fronteiras taxonômicas (`informatica e games` com 112 produtos; `TV E SOM` com 111 produtos).
  * **340 produtos (11,33%):** Ruído informacional total sem especificação de ramo (`DIVERSOS` com 116, `OUTROS` com 121 e campo vazio com 103).

---

### 6.3. Alternativas Consideradas

* **Alternativa 1 — Descartar produtos com categorias ambíguas ou genéricas:**
  * *Por que foi descartada:* Causaria a perda imediata de 340 produtos ativos que possuem vendas registradas no legado, quebrando a integridade referencial de dezenas de milhares de itens de pedidos em `fato_item_pedido`.
* **Alternativa 2 — Inferência Heurística por Mineração de Texto na Descrição:**
  * *Por que foi descartada:* Introduz regras arbitrárias e opacas (*black-box*) com alto índice de erro e sem garantia de auditabilidade, violando o princípio pedagógico do laboratório.
* **Alternativa 3 — Normalização Determinística com Preservação de Evidência Bruta:**
  * *Decisão:* **Adotada**. Mapear rigorosamente os sinônimos, assumir a agregação no nível superior para termos híbridos, alocar os genéricos em `Outros` e reter 100% do texto original na coluna `categoria_origem`.

---

### 6.4. Justificativa e Racionalidade Técnica
Garante integridade referencial total (nenhum produto ou item faturado é descartado) e estabelece consistência para relatórios agregados por departamento, mantendo transparência documental absoluta sobre o que foi possível conformar e o que a tecnologia legada omitiu.

---

### 6.5. O que se Perde e Trade-offs
Perde-se a especificidade de subcategoria para 563 produtos do legado (18,77% da base legada), que passam a ser analisados apenas pelo macro-departamento ou sob a rubrica `Outros`.

---

### 6.6. Registros Afetados
* **15.000 produtos conformados** em `dw.dim_produto` (3.000 do legado e 12.000 do e-commerce).
* **340 produtos** do legado classificados sob a categoria `Outros`.
* **223 produtos** híbridos alocados no nível hierárquico superior.
* **Tabelas De-Para criadas:** `stg.map_produto_legado` (3.000 mapeamentos) e `stg.map_produto_ecom` (12.000 mapeamentos) para chave substituta `produto_sk`.

---

### 6.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("total de produtos dim_produto", 15000)`: integridade de catálogo 100% preservada.
* `qa.dominio("origem do produto em {LEGADO,ECOM}")`: consistência da procedência dimensional.
* `qa.igual("produtos em categoria Outros", 340)`: rastreabilidade exata dos produtos sem classificação.

---

## 7. Decisão 5 — Tratamento de Datas, Sentinelas e Fusos Horários

A integridade cronológica das transações é um requisito basilar para modelos preditivos de mineração de dados. Para prever a recompra em uma janela fixa (`JANELA_ALVO_DIAS = 90`) a partir de um ponto de corte estrito (`DATA_CORTE = 2025-06-30`), qualquer distorção de fusos horários ou inconsistência de datas corrompe a classificação temporal dos eventos.

No código de transformação (`02_transformacao.py` — função `trata_datas_e_ausencias`), esta decisão compreende duas fichas metodológicas:
* **Ficha RDT-08:** Classificação epistêmica de ausências, eliminação do sentinela `1900-01-01` e anulação seletiva de prazos de entrega negativos.
* **Ficha RDT-09:** Padronização canônica de fusos horários em UTC.

---

### 7.1. Ficha RDT-08 — Classificação de Ausências, Sentinelas e Inconsistências Temporais

#### 7.1.1. A Decisão
1. **Classificação Epistêmica das Ausências:** Distinção rigorosa entre Ausência Não Aplicável (pedidos não entregues com `data_entrega = NULL`), Ausência Não Coletada (clientes sem CPF mantidos como `NULL` na dimensão) e Valores Sentinela de ERP.
2. **Eliminação do Sentinela `1900-01-01`:** Conversão da data de entrega sentinela do legado para `NULL`.
3. **Inconsistência Cronológica (`data_entrega < data_pedido`):** Preservação do registro da data física informada pela origem em `data_entrega`, porém com anulação da métrica analítica derivada (`dias_entrega = NULL`) para não gerar prazos negativos no DW.
4. **Chamados do SAC em Aberto:** Manutenção de `data_fechamento = NULL` para chamados sem data de encerramento.

* **Script associado:** `02_transformacao.py` (função `trata_datas_e_ausencias`).

#### 7.1.2. O que o Dado Mostrava (Evidência Quantificada)
* **Sentinela `1900-01-01`:** No legado, exatamente **1.025 pedidos (0,79% da base)** possuem `DT_ENTREGA = '1900-01-01 00:00:00'`. Destes, 100% possuem `STATUS = 'ENTREGUE'`. Trata-se de artifício do ERP antigo para contornar a obrigatoriedade de preenchimento (`NOT NULL`) quando a data real da transportadora era desconhecida.
* **Inversão Cronológica:** Em **2.458 pedidos** do DW (775 no legado e 1.683 no e-commerce, representando exatamente 0,60% dos pedidos de cada origem), a data de entrega é anterior à data de realização do pedido, gerando prazos negativos absurdos decorrentes de descalibração de relógio de servidor ou erro operacional de digitação.
* **SAC Não Concluído:** No arquivo de atendimentos, **5.856 chamados (6,09% dos 96.140 atendimentos)** possuem o campo `data_fechamento` vazio ou preenchido com string `'NULL'`.

#### 7.1.3. Alternativas Consideradas
* **Alternativa 1 — Manter a data `1900-01-01` e computar prazos negativos:**
  * *Por que foi descartada:* Erro técnico grosseiro. Produziria prazos médios de entrega de aproximadamente **-45.000 dias**, inviabilizando qualquer agregação analítica ou cálculo de ansiedade do consumidor para a modelagem de retenção.
* **Alternativa 2 — Imputação Estatística pela Média ou Mediana:**
  * *Por que foi descartada:* Viola o princípio epistemológico fundamental da disciplina: imputar a média inventa uma entrega pontual fictícia e mascara pedidos problemáticos que concentram falhas operacionais e insatisfação no SAC.
* **Alternativa 3 — Conversão de Sentinela para `NULL` e Anulação Seletiva da Métrica Derivada:**
  * *Decisão:* **Adotada**. Converte `1900-01-01` para `NULL` e define `dias_entrega = NULL` para entregas cronologicamente invertidas, mantendo a integridade da data física no histórico.

#### 7.1.4. Justificativa e Racionalidade Técnica
Garante que a métrica `dias_entrega` respeite a restrição matemática `dias_entrega >= 0` em 100% dos pedidos do DW, prevenindo viés em modelos preditivos sem gerar distorções artificiais por imputação estatística cega.

#### 7.1.5. O que se Perde e Trade-offs
A data real de entrega dos 1.025 pedidos do legado é irrecuperável. Esses pedidos passam a ser excluídos de análises estritas de prazo de entrega logístico.

#### 7.1.6. Registros Afetados
* **1.025 pedidos** com sentinela `1900-01-01` convertidos para `NULL`.
* **2.458 pedidos** com inconsistência cronológica que tiveram `dias_entrega` ajustado para `NULL`.
* **5.856 atendimentos** do SAC preservados como chamados em andamento.

#### 7.1.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("prazos de entrega negativos no DW", 0)`: zero pedidos com prazos negativos.
* `qa.igual("sentinelas 1900-01-01 em data_entrega", 0)`: 100% dos sentinelas 1900 eliminados.
* `qa.igual("pedidos com entrega anterior ao pedido com dias_entrega NULL", 2458)`: conformidade exata das anulações.

---

### 7.2. Ficha RDT-09 — Padronização de Fuso Horário e Harmonização Temporal

#### 7.2.1. A Decisão
Padronização universal em **UTC** de todos os carimbos de data/hora transacionais ingeridos no Data Warehouse, com truncamento para data civil no grão diário (`DATE`) na dimensão de tempo `dw.dim_tempo`.

* **Script associado:** `01_extracao.py` e `02_transformacao.py`.

#### 7.2.2. O que o Dado Mostrava (Evidência Quantificada)
* A plataforma de e-commerce armazena eventos com `TIMESTAMPTZ` (UTC explícito).
* O sistema legado registrava timestamps em `DATETIME` nativo do MySQL (horário civil local de Cuiabá/MT, UTC-04:00, ou Brasília, UTC-03:00, sem carimbo de fuso).
* A falta de harmonização geraria uma distorção de 3 a 4 horas em comparações horárias, alterando o dia civil de pedidos efetuados no fim da noite e desalinhando eventos cruzados com chamados do SAC.

#### 7.2.3. Alternativas Consideradas
* **Alternativa 1 — Descartar fusos e converter tudo para data local ingênua:**
  * *Por que foi descartada:* Gera ambiguidade em transações interestaduais e quebra a rastreabilidade de logs de auditoria técnica.
* **Alternativa 2 — Padronização Canônica em UTC:**
  * *Decisão:* **Adotada**. Assume UTC como referência universal corporativa do Data Warehouse.

#### 7.2.4. Justificativa e Racionalidade Técnica
Segue a convenção moderna da engenharia de dados, assegurando que o ponto de corte do projeto (`DATA_CORTE = 2025-06-30 23:59:59 UTC`) se aplique com exatidão matemática sobre todas as transações de todas as fontes.

#### 7.2.5. O que se Perde e Trade-offs
Pedidos realizados entre 20h e 23h59 no horário de Cuiabá passam a ter sua data de calendário civil registrada no dia seguinte em UTC, o que exige atenção em análises de pico de vendas por hora.

#### 7.2.6. Registros Afetados
* **410.000 pedidos** e **160.000 avaliações do marketplace** harmonizados temporalmente em UTC.

#### 7.2.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* Preservação da integridade de datas em `dw.dim_tempo` e conformidade com os cortes temporais da ABT.

---

## 8. Decisão 6 — Ligação das Fontes de Arquivo ao DW (Ficha RDT-13)

### 8.1. A Decisão
Adoção de chaves compostas de ligação referencial para integrar as fontes externas em arquivo ao repositório analítico:
1. **Atendimentos do SAC:** Associação a `dw.fato_pedido` através da chave composta `(origem_sistema, id_pedido_origem)` com prefixos padronizados (`LEG-<id>` e `ECOM-<id>`), e associação a `dw.dim_cliente` prioritariamente pelo CPF normalizado (93,77% dos casos) e, na sua ausência, indiretamente através do cliente cadastrado no pedido vinculado (6,23% dos casos).
2. **Avaliações do Marketplace:** Associação direta a pedidos via `order.ref` (`LEG-<id>` e `ECOM-<id>`) e a produtos via `product.sku` (`SKU-<n>` e `LEG-<id>`).
3. **Política de Descarte:** **Descarte zero**. Como a auditoria de cobertura revelou 100,00% de correspondência com eventos comerciais faturados, nenhum registro de arquivo é descartado.

* **Script associado:** `02_transformacao.py` (função `liga_sac_e_avaliacoes`).

---

### 8.2. O que o Dado Mostrava (Evidência Quantificada)
* **SAC (`atendimentos_sac.csv` — 96.140 chamados):**
  * **Ligação com Pedidos:** Exatamente **96.140 de 96.140 chamados (100,00%)** conectam perfeitamente a pedidos faturados no DW. Não existem tickets órfãos ou chamados de pré-venda avulsos.
  * **Ligação com Clientes:** 90.155 chamados (93,77%) possuem CPF informado no atendimento. Os 5.985 chamados restantes (6,23%) omitiram o documento na abertura, mas possuem o código do pedido válido em mãos.
* **Avaliações do Marketplace (`avaliacoes_marketplace.json` — 160.000 objetos):**
  * **Ligação com Pedidos:** Exatamente **160.000 de 160.000 avaliações (100,00%)** conectam com pedidos reais (40.016 do legado e 119.984 do e-commerce).
  * **Ligação com Produtos:** Exatamente **160.000 de 160.000 avaliações (100,00%)** conectam aos produtos cadastrados em `dw.dim_produto`.

---

### 8.3. Alternativas Consideradas

* **Alternativa 1 — Descartar os 5.985 chamados de suporte sem CPF:**
  * *Por que foi descartada:* Descartaria 6,23% dos chamados de suporte, enfraquecendo variáveis preditivas de atrito e insatisfação justamente para clientes que enfrentaram problemas graves com entregas ou produtos defeituosos.
* **Alternativa 2 — Manter chamados sem CPF com `cliente_sk = NULL`:**
  * *Por que foi descartada:* Perderia o vínculo causal entre o atrito registrado no atendimento e o histórico do cliente na modelagem de propensão à recompra.
* **Alternativa 3 — Resolução Indireta da Autoria via Cabeçalho do Pedido:**
  * *Decisão:* **Adotada**. Como o pedido está identificado sem ambiguidade, herda-se o `cliente_sk` titular da compra para atribuir a autoria do chamado telefônico.

---

### 8.4. Justificativa e Racionalidade Técnica
Preserva 100% das métricas de sentimento (notas de satisfação e reviews) e de fricção operacional (horas de resolução e chamados abertos), atribuindo com lastro factual cada chamado ao cliente real através da rastreabilidade do pedido faturado.

---

### 8.5. O que se Perde e Trade-offs
Assume-se a premissa de que a pessoa física que ligou para o SAC a respeito de uma entrega é a própria titular cadastrada no pedido de compra (o que é a prática padrão de atendimento no comércio varejista).

---

### 8.6. Registros Afetados
* **96.140 atendimentos do SAC** conformados e integrados na tabela intermediária `stg.sac_conformado`.
* **160.000 avaliações de clientes** conformadas e integradas em `stg.avaliacoes_conformadas`.
* **0 registros descartados** (100% de aproveitamento das duas fontes).

---

### 8.7. Asserções Associadas no Framework (`qa.execucao_assercao`)
* `qa.igual("cobertura SAC -> pedido no DW", 96140)`: 100% dos chamados vinculados a pedidos.
* `qa.igual("cobertura avaliacoes -> pedido no DW", 160000)`: 100% das avaliações vinculadas a pedidos.
* `qa.igual("cobertura avaliacoes -> produto no DW", 160000)`: 100% das avaliações vinculadas a produtos.

---

## Referências e Reprodução

* **Documentos e Referenciais:** *Projeto Prático de ETL Mercatto Varejo (2026/2)*, Seção 3.2; *ETL como Preparação de Dados na Mineração de Dados*, Seção 6 (Princípios de Desenho); Dicionário de Dados do Laboratório.
* **Scripts Executáveis:** [`01_extracao.py`] e [`02_transformacao.py`], localizados na pasta `lab-etl-varejo/etl/`.
* **Comandos de Reprodução (Ambiente Docker):**
  ```bash
  docker compose exec etl python 01_extracao.py
  docker compose exec etl python 02_transformacao.py
  ```
* **Auditoria de Qualidade:** Os resultados das 31 asserções de integridade estão persistidos no banco de dados analítico e podem ser consultados via SQL:
  ```sql
  SELECT etapa, nome, valor_obtido, valor_esperado, aprovado, executado_em 
  FROM qa.execucao_assercao 
  WHERE etapa IN ('01_extracao', '02_transformacao') 
  ORDER BY id ASC;
  ```

