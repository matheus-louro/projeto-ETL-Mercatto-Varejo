# Registro de Decisões de Transformação (RDT) — Documento Integral

**Mineração de Dados · Engenharia de Computação · IFMT — 2026/2**  
**Projeto Prático de ETL — Mercatto Varejo**  
**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi  
**Versão do Pipeline:** 1.0.0 (Entrega Final — Semana 4)  
**Ambiente:** Docker, Escala 1.0, Semente `20262`

---

## Apresentação e Escopo Geral

Este documento consolida o **Registro de Decisões de Transformação (RDT)** integral do Projeto Prático Mercatto Varejo, cobrindo as 17 decisões técnicas e conceituais formuladas ao longo das quatro semanas de desenvolvimento do pipeline de ETL e mineração de dados.

Seguindo o referencial teórico da disciplina, o RDT documenta formalmente não o que o código faz, mas **por que** cada transformação foi desenhada, **quais alternativas** foram ponderadas, **o que se perdeu** em cada escolha e a **quantificação exata** dos registros impactados.

O documento abrange desde a ingestão completa na camada de staging (`stg`), passando pela conformação semântica (`cfm`), carga atômica do esquema estrela analítico (`dw`), quarentena e rastreabilidade (`aud`), construção da Tabela-Base de Análise correta e com vazamento (`abt`) e o histórico de qualidade (`qa`).

---

## RDT-01 — Carga completa e fidelidade da extração

**Etapa:** `01_extracao.py`.

**Evidência.** As quatro fontes somam 2.205.864 registros, incluindo as 21 categorias digitais. Não há uma coluna confiável de última atualização em todas as tabelas. `DT_CADASTRO`, `created_at` e datas de pedidos representam eventos, não garantem a captura de alterações posteriores. Os arquivos não fornecem contrato de captura de mudanças.

**Alternativas.** (1) Incremental pela data do evento: reduz leitura, mas pode omitir atualizações antigas e não cobre tabelas sem esse atributo. (2) Comparação de hashes ou captura de mudanças: possível com infraestrutura adicional, exige controlar exclusões e manter estado. (3) Carga completa em lotes: adotada pela simplicidade verificável e volume tratável.

**Decisão e justificativa.** Substituir integralmente cada tabela de staging, com gravação transacional por tabela e lotes de 10.000 registros. Tipos relacionais são refletidos e mapeados para equivalentes no PostgreSQL: DECIMAL permanece exato, datas e timestamps mantêm seus tipos. O CSV é lido como texto, preservando vazios, sentinelas e quebras internas. No NDJSON, nomes e objetos originais ficam em colunas JSONB; o registro textual completo também é preservado. Omissão de chave, `null` JSON, número e string continuam distinguíveis. Acrescentam-se `_fonte`, `_extraido_em` e `_linha_origem`; a última coluna é ordinal de registro lógico.

**O que se perde.** A substituição não mantém fotografias de execuções anteriores em `stg`; mudanças históricas da origem não podem ser reconstruídas por essa camada. Há custo de reler 100% da base. Os valores da fotografia corrente são preservados.

**Registros afetados.** 2.205.864 (100% da extração):

| Tabela / arquivo de origem | Registros |
|---|---:|
| `CLIENTES` | 47.250 |
| `PRODUTOS` | 3.000 |
| `PEDIDOS` | 130.000 |
| `ITENS_PEDIDO` | 397.086 |
| `shop.customer` | 85.000 |
| `shop.category` | 21 |
| `shop.product` | 12.000 |
| `shop.orders` | 280.000 |
| `shop.order_item` | 995.367 |
| SAC CSV | 96.140 |
| Avaliações NDJSON | 160.000 |

**Asserções associadas.** `linhas <tabela>` compara contagem gravada e lida; `conteudo fiel <tabela>` compara SHA-256 dos valores ordenados. `JSON distingue omissao null e tipos` compara cada campo ao documento original. Identificadores de arquivo são verificados separadamente. Falhas encerram a execução com código diferente de zero e são registradas em `qa.execucao_assercao`.

---

## RDT-02 — Identidade de clientes entre sistemas

**Etapa:** `transformacoes_semana2.unifica_clientes`.

**Evidência.** Os 47.250 registros do legado e 85.000 do e-commerce compartilham 12.605 CPFs normalizados distintos. Destes, 1.135 (9,00%) têm dígitos verificadores inválidos. Há 4.423 registros sem CPF utilizável no legado (9,36%) e 6.855 no e-commerce (8,06%). Nomes repetidos impedem considerar igualdade de nome como prova de identidade.

**Alternativas.** (1) Parear apenas CPFs válidos: remove identificadores formalmente incorretos, mas perde 1.135 correspondências observáveis. (2) Pareamento aproximado por nome, cidade e UF: pode recuperar casos sem CPF, mas requer validação de falsos positivos, não realizada. (3) CPF exato normalizado, válido ou inválido, mantendo separados registros sem CPF: adotada.

**Decisão e justificativa.** Usar os 11 dígitos como identificador candidato, manter `cpf_valido` e registrar o método em `regra_pareamento`. Ausências permanecem isoladas por sistema e ID. Igualdade de CPF é uma regra operacional, não confirmação independente de pessoa real. IDs internos de sistemas diferentes não são usados para parear pessoas por igualdade numérica.

**O que se perde.** Pessoas presentes nas duas fontes sem CPF comum podem permanecer fragmentadas; sua quantidade real não é determinável apenas pelas correspondências observadas. CPFs compartilhados podem conter colisões. A validade formal e esse risco não são ocultados.

**Registros afetados.** 132.250 registros de origem (100%) processados; dimensão resultante com 118.215 linhas:

| Origem da identidade | Linhas | % da dimensão |
|---|---:|---:|
| AMBOS | 12.605 | 10,66% |
| LEGADO | 33.218 | 28,10% |
| ECOM | 72.392 | 61,24% |

**Asserções associadas.** `cpf sem duplicatas entre validos`, `cpf sem duplicatas entre invalidos`, `origem unificacao`, `cardinalidade clientes` e `CPF ausente nao foi unificado entre pessoas`.

---

## RDT-03 — Duplicatas internas e mapeamento de todos os IDs

**Etapa:** `transformacoes_semana2.unifica_clientes`.

**Evidência.** A normalização encontra 1.427 registros excedentes por CPF no legado e três no e-commerce. Os três IDs digitais excedentes são referenciados por 14 pedidos. Duplicação por CPF e duplicação por nome não são tratadas como o mesmo problema.

**Alternativas.** (1) Excluir excedentes sem mapeamento: simplifica a dimensão, mas deixa pedidos sem destino para seus IDs. (2) Deduplicar registros sem CPF por similaridade: recupera possíveis duplicatas com risco de fusão não validado. (3) Eleger menor ID por CPF dentro de cada origem e preservar todos os aliases: adotada.

**Decisão e justificativa.** Todos os IDs ficam em `cfm.clientes_origem` e nos mapas `cfm.map_cliente_legado` e `cfm.map_cliente_ecom`, inclusive duplicatas e ausências. Nos atributos da identidade unificada, prioriza-se o cadastro canônico digital quando existe; cidade disponível pode vir do legado, e `dt_primeiro_cadastro` usa a menor data registrada no grupo. Nomes são normalizados; cidade `N/A` não é tratada como cidade válida.

**O que se perde.** A dimensão apresenta um único conjunto de atributos, suprimindo variações secundárias na visão integrada. Atributos e IDs originais continuam acessíveis em `stg` e nos mapas. Duplicatas sem CPF não são removidas por suposição de identidade.

**Registros afetados.** 1.427 registros colapsados no legado (3,02% de 47.250), resultando em 45.823 identidades dessa origem antes da integração. No e-commerce, três (0,0035% de 85.000) são colapsados. Os mapas preservam 47.250/47.250 IDs legados e 85.000/85.000 digitais (100% em cada origem), cobrindo os 410.000 pedidos.

**Asserções associadas.** `mapa completo clientes legado`, `mapa completo clientes ecommerce`, `pedidos sem mapa de cliente` e verificações de unicidade de CPF. A cobertura não é limitada aos IDs canônicos.

---

## RDT-04 — Conformação dos status

**Etapa:** `transformacoes_semana2.conforma_status`.

**Evidência.** O legado agrega cancelamento e recusa de pagamento em `CANCELADO`; a distinção digital é informada pelo esqueleto do laboratório. As distribuições medidas são:

| Origem e status | Pedidos | % na origem | Macrostatus / motivo |
|---|---:|---:|---|
| LEGADO: `ENTREGUE` | 101.192 | 77,84% | ENTREGUE / não aplicável |
| LEGADO: `CANCELADO` | 15.774 | 12,13% | CANCELADO / desconhecido |
| LEGADO: `EM TRANSITO` | 7.798 | 6,00% | EM_TRANSITO / não aplicável |
| LEGADO: `SEPARACAO` | 5.236 | 4,03% | SEPARACAO / não aplicável |
| ECOM: `delivered` | 207.204 | 74,00% | ENTREGUE / não aplicável |
| ECOM: `canceled` | 22.413 | 8,00% | CANCELADO / SOLICITACAO_CLIENTE |
| ECOM: `payment_declined` | 13.990 | 5,00% | CANCELADO / RECUSA_PAGAMENTO |
| ECOM: `shipped` | 22.375 | 7,99% | EM_TRANSITO / não aplicável |
| ECOM: `processing` | 14.018 | 5,01% | SEPARACAO / não aplicável |

**Alternativas.** (1) Um único CANCELADO, descartando o motivo digital. (2) Macrostatus separados para cada motivo, com categoria desconhecida no legado. (3) Macrostatus comum e motivo secundário: adotada.

**Decisão e justificativa.** `dw.dim_status` mantém status original e sistema, além de `status_conformado` e `motivo_cancelamento`. O motivo fica NULL no legado; a interpretação de `canceled` segue a convenção do kit. A hierarquia permite comparar cancelamentos agregados sem eliminar a distinção disponível no e-commerce.

**O que se perde.** A consulta somente ao macrostatus não distingue causas. O detalhe do legado é desconhecido e não é imputado. As categorias não demonstram, por si, efeitos causais sobre recompra.

**Registros afetados.** 410.000 pedidos (100%); 52.177 são cancelados/recusados (12,73% do conjunto), sendo 15.774 legados e 36.403 digitais. Há nove combinações de sistema e status de origem.

**Asserções associadas.** `status de origem sem mapeamento`, `nove status de origem` e restrição de unicidade `(status_origem,sistema)` da dimensão.

---

## RDT-05 — Semântica monetária e definição das medidas

**Etapa:** `transformacoes_semana2.conforma_valores`.

**Evidência.** O legado registra total líquido com frete; o e-commerce registra itens líquidos sem frete. Os itens foram agregados por pedido antes da junção ao cabeçalho, excluindo apenas os órfãos da comparação com cabeçalhos. Todos os status foram incluídos. Após a hipótese da RDT-06, 130.000/130.000 e 280.000/280.000 pedidos fecham, respectivamente, com resíduo máximo de R$ 0,00.

**Alternativas.** (1) Copiar totais sem conformação: mistura grandezas. (2) Padronizar somente o líquido de mercadorias: útil para algumas análises, exige consultar frete separadamente. (3) Disponibilizar mercadoria bruta, desconto, frete e total com definições explícitas: adotada para permitir ambas as leituras e seguir o contrato do destino.

**Decisão e justificativa.** `valor_mercadoria = Σ(quantidade × valor_unitario)` é **bruto**, sem frete e antes de desconto. `valor_desconto` soma descontos efetivos; `valor_total = valor_mercadoria + valor_frete - valor_desconto`. O líquido dos itens é `valor_mercadoria - valor_desconto`. Isso evita subtrair desconto duas vezes na carga posterior. `valor_total_origem` e `sistema_origem` são preservados.

| Medida (R$) | Legado | E-commerce |
|---|---:|---:|
| Total registrado na origem | 281.084.957,13 | 734.859.099,95 |
| Mercadoria bruta | 292.680.195,13 | 794.473.859,71 |
| Desconto efetivo | 17.356.170,57 | 59.614.759,76 |
| Frete | 5.760.932,57 | 10.991.760,38 |
| Total conformado com frete | 281.084.957,13 | 745.850.860,33 |

**O que se perde.** O nome “total” deixa de ser interpretável sem a definição de origem: o campo integrado tem significado comum, enquanto o valor anterior exige consultar `valor_total_origem`. Não há descarte intencional de valores de cabeçalho nem da decomposição financeira.

**Registros afetados.** 410.000 pedidos (100%). Todos os 1.392.453 itens são mantidos na conformação; 20.577 órfãos permanecem identificáveis para decisão na Semana 3 e não são atribuídos a pedidos fictícios.

**Asserções associadas.** `cardinalidade pedidos preservada`, `cardinalidade itens preservada`, `reconciliacao por pedido com origem`, `mercadoria bruta menos desconto igual itens liquidos` e `total igual mercadoria mais frete menos desconto` (tolerância de R$ 0,01 nas comparações com origem/itens).

---

## RDT-06 — Desconto sentinela e frete negativo

**Etapa:** `transformacoes_semana2.conforma_valores`.

**Evidência.** 4.056 itens legados (1,02% dos 397.086) contêm desconto `-1`, distribuídos por 4.003 pedidos (3,08% dos 130.000). Subtrair literalmente esse valor adicionaria R$ 1,00 por item. Há frete negativo em 362 pedidos legados (0,28%) e 812 digitais (0,29%), total de 1.174/410.000 (0,29%).

**Alternativas.** (1) Tratar `-1` como desconto real: cria acréscimo incompatível com a reconciliação. (2) Anular desconto e totais desses pedidos: explicita incerteza, mas impede reconciliar medidas disponíveis. (3) Zero efetivo com indicador de ausência: adotada por fechar os cabeçalhos sem afirmar que o desconto real foi zero. Para frete, foram consideradas a exclusão dos pedidos, a substituição por zero e a preservação do sinal; adotou-se preservar.

**Decisão e justificativa.** Somente o sentinela `-1` vira zero efetivo, com `desconto_nao_informado=TRUE`. Outros descontos não são truncados indiscriminadamente. O frete mantém valor e sinal, permitindo reconciliação. Não há evidência suficiente para afirmar que represente crédito, subsídio ou erro: sua causa permanece desconhecida.

**O que se perde.** O desconto real não é recuperável. Uma análise que ignore o indicador confundirá ausência com desconto zero. Preservar fretes negativos pode manter defeitos da origem, mas evita inventar receita ou apagar sua ocorrência.

**Registros afetados.** 4.056 itens (1,02% do legado) recebem desconto efetivo zero e indicador; 1.174 pedidos (0,29% do conjunto) mantêm frete negativo.

**Asserções associadas.** `nenhum desconto sentinela conformado`, `frete preserva valor e sinal da origem` e `reconciliacao por pedido com origem`.

---

## RDT-07 — Taxonomia de produtos e atributo de atividade

**Etapa:** `transformacoes_semana2.conforma_categorias`.

**Evidência.** Há 27 rótulos distintos para 3.000 produtos legados e 21 nós (8 raízes, 13 filhos) para 12.000 digitais. Os casos híbridos são 112 produtos em `informatica e games` (3,73% do legado) e 111 em `TV E SOM` (3,70%). `DIVERSOS`, `OUTROS` e vazio somam 340 (11,33%). O atributo ATIVO contém 340 valores N (11,33%), que não podem ser convertidos por `bool("N")`.

**Alternativas.** (1) Excluir produtos ambíguos/genéricos: perde catálogo e vínculos dos itens. (2) Inferir categoria específica pela descrição: pode recuperar detalhe, exige validação adicional. (3) Mapear de forma determinística, preservando categoria original e indicadores: adotada.

**Decisão e justificativa.** Adota-se a árvore digital; variantes de grafia são uniformizadas para consultar o mapa. `TV E SOM` fica em `Áudio e TV`, sem subcategoria. `informatica e games` fica em `Informática`, sem subcategoria, como escolha operacional explícita: não é uma correspondência sem perda nem o pai comum dos dois ramos. Genéricos ficam em `Outros`. Rótulos amplos `TELEFONIA` e `AUDIO/VIDEO` não são reduzidos artificialmente a `Smartphones` ou `Áudio`. Preservam-se `categoria_origem` e indicadores de ambiguidade. IDs de produtos entre sistemas não são equiparados. S vira TRUE e N FALSE.

**O que se perde.** A projeção do rótulo híbrido em Informática não representa a participação de games; análises somente pela categoria conformada omitem esse aspecto. Categorias amplas/genéricas não permitem reconstruir subcategorias. O texto original permite auditar a escolha.

**Registros afetados.** 15.000 produtos (100%); 223 híbridos (7,43% dos 3.000 legados), 340 genéricos (11,33%) e 340 inativos legados corretamente preservados (11,33%). Mapas cobrem 3.000 IDs legados e 12.000 digitais (100%).

**Asserções associadas.** `cardinalidade produtos preservada`, `categoria origem preservada`, `sku de produto unico` e `ativo S e N corretamente mapeados`.

---

## RDT-08 — Classificação e tratamento de ausências e valores inválidos

**Etapas:** `unifica_clientes`, `conforma_valores`, `trata_datas_e_ausencias`, `liga_sac_e_avaliacoes` e `inventaria_ausencias`.

**Evidência.** O inventário completo distingue NULL SQL, vazio textual, chave omitida, null JSON e sentinelas. Foram observadas as seguintes ausências/sentinelas nas fontes brutas, antes da deduplicação do SAC:

| Fonte / campo | Representação | Ocorrências / base | Percentual |
|---|---|---:|---:|
| Legado: CPF | Vazio | 4.423 / 47.250 | 9,36% |
| Legado: CIDADE | N/A | 933 / 47.250 | 1,97% |
| Legado: CATEGORIA | Vazio | 103 / 3.000 | 3,43% |
| Legado: DT_ENTREGA | NULL SQL | 28.808 / 130.000 | 22,16% |
| Legado: DT_ENTREGA | 1900-01-01 | 1.025 / 130.000 | 0,79% |
| Legado: VL_DESCONTO | -1 | 4.056 / 397.086 | 1,02% |
| E-commerce: tax_id | NULL SQL | 6.855 / 85.000 | 8,06% |
| E-commerce: parent_id | NULL SQL (raiz) | 8 / 21 | 38,10% |
| E-commerce: delivered_at | NULL SQL | 72.796 / 280.000 | 26,00% |
| SAC: data_fechamento | Vazio | 5.856 / 96.140 | 6,09% |
| SAC: nota_satisfacao | Vazio | 8.682 / 96.140 | 9,03% |
| JSON: rating | Chave omitida | 4.831 / 160.000 | 3,02% |
| JSON: title | Chave omitida | 24.264 / 160.000 | 15,17% |
| JSON: comment | Chave omitida | 47.814 / 160.000 | 29,88% |
| JSON: verified_purchase | Chave omitida | 15.731 / 160.000 | 9,83% |
| JSON: helpful_votes | Chave omitida | 72.129 / 160.000 | 45,08% |

Não foram observados nulls JSON explícitos nesses campos; sua distinção de omissão permanece preservada na estrutura de ingestão. `rating` aparece como string em 16.108 avaliações (10,07%), situação de heterogeneidade de tipo, não ausência.

**Alternativas.** (1) Preencher com zero, FALSE, média ou data estimada: fornece valores, mas mistura desconhecido e observado. (2) Excluir registros incompletos: simplifica cálculos, perde cobertura e pode introduzir viés. (3) Manter NULL, distinguir causas observáveis e criar indicadores: adotada; o desconto tem a hipótese financeira específica da RDT-06.

**Decisão e justificativa.**

- CPF não coletado: NULL normalizado e identidade separada. Cidade N/A: excluída da escolha de cidade válida; a identidade pode obter cidade de outro cadastro do grupo. Categoria vazia: Outros, mantendo a falta de especificação.
- `parent_id` nulo: não aplicável a categoria raiz, preservado. Entrega nula em pedido não entregue: evento não ocorrido/não aplicável conforme status; não se atribui automaticamente essa causa a pedidos entregues sem data.
- Entrega 1900-01-01: NULL com `entrega_sentinela` e `entrega_sem_data`. Não há NOT NULL na origem que prove por que o sentinela foi adotado.
- Entrega anterior ao pedido: anular data e prazo na visão conformada, com `entrega_inconsistente`; a data original permanece em stg. São 775 casos legados (0,60%) e 1.683 digitais (0,60%).
- SAC sem encerramento registrado: data NULL e indicador, sem afirmar que ainda está aberto. Há 5.856 linhas brutas (6,09%); após deduplicação, 5.791/95.000 (6,10%).
- Nota não coletada ou rating omitido: NULL, sem imputação. Nota fora de 1 a 5: NULL e indicador; no SAC deduplicado, 2.800/95.000 (2,95%) são inválidas.
- Tempo de resolução negativo: NULL e `tempo_resolucao_invalido`, não zero horas. As 353 linhas brutas (0,37% de 96.140) correspondem a 350 protocolos únicos (0,37% de 95.000).
- JSON opcional: texto omitido não é inventado; compra verificada ausente é desconhecida, não FALSE; votos ausentes não são zero. Rating numérico e string são convertidos ao mesmo inteiro apenas na conformação. Stg preserva tipos, omissão e null explícito.

**O que se perde.** Valores reais desconhecidos não são recuperados; métricas calculadas apenas sobre observações válidas podem ter viés de seleção. Indicadores e cópias brutas conservam o motivo observável da exclusão analítica. Estado “aberto” e causa da falha não são inferidos sem evidência.

**Registros afetados.** Bases e percentuais por campo estão na tabela. Um registro pode ter várias anomalias; as contagens não são somáveis. Além das 1.025 sentinelas (0,79% do legado), 2.458/410.000 inversões (0,60%) são anuladas com indicadores. Bases bruta e deduplicada do SAC são declaradas separadamente.

**Asserções associadas.** `ausencias sem regra de tratamento`, `cidade N/A nao e cidade valida`, `CPF ausente nao foi unificado entre pessoas`, `sentinela de entrega sinalizada e anulada`, `entrega valida nunca anterior ao pedido`, `horas negativas anuladas e sinalizadas`, `notas conformadas no dominio` e `nota JSON ausente mantida NULL`.

---

## RDT-09 — Fusos horários, UTC e dia de negócio

**Etapas:** `conforma_valores`, `trata_datas_e_ausencias` e `liga_sac_e_avaliacoes`.

**Evidência.** O legado usa timestamps sem fuso; o e-commerce fornece instantes TIMESTAMPTZ. No JSON, 31.915/160.000 horários (19,95%) não informam offset. Converter tudo ao dia UTC sem critério muda o dia civil de 44.184/410.000 pedidos (10,78%), sendo 9.290 legados e 34.894 digitais.

**Alternativas.** (1) Ignorar offsets e comparar horários ingênuos: mistura instantes. (2) Assumir Cuiabá para todos os horários sem fuso: defensável com confirmação da operação local, indisponível. (3) Assumir `America/Sao_Paulo` para horários sem fuso, guardar instantes em UTC e conservar o dia de negócio nessa zona: adotada como convenção explícita.

**Decisão e justificativa.** O fuso assumido é hipótese, não descoberta comprovada. Horários legados recebem essa zona; os digitais preservam o instante; avaliações respeitam offset quando disponível, e as demais recebem a hipótese e `fuso_assumido=TRUE`. Usam-se timestamps com fuso. `data_pedido_local`, `data_entrega_local` e data civil de avaliação são derivadas em America/Sao_Paulo. DATA_CORTE continua 30/06/2025: o corte diário deve usar a data local de negócio, sem redefinir silenciosamente o contrato para meia-noite UTC. O SAC informa somente datas e não recebe um horário artificial.

**O que se perde.** O fuso verdadeiro dos horários ingênuos é irrecuperável sem informação externa. A hipótese pode deslocar eventos se a origem operava em outra zona; string/data bruta e indicador tornam o risco auditável. A data diária perde o horário, por isso o timestamp completo também é mantido.

**Registros afetados.** 410.000 pedidos (100%) e 160.000 avaliações (100%) recebem representação uniforme. A hipótese aplica-se a 130.000 horários de pedido legados (100% dessa origem) e 31.915 avaliações (19,95% do JSON). A fronteira de corte também é verificada às 23h59min59s.

**Asserções associadas.** `UTC legado representa horario local assumido`, `UTC ecommerce preserva instante original`, `JSON sem fuso recebe zona assumida`, `JSON com fuso preserva instante` e `fronteira do corte em horario de negocio`.

---

## RDT-10 — Itens sem pedido correspondente

**Etapa:** 03, carga de itens.

**Evidência.** Dos 1.392.453 itens conformados, 20.577 não encontram pedido
no respectivo sistema. São 5.868 de 397.086 itens legados (1,4778%) e 14.709 de
995.367 itens digitais (1,4777%). Seus valores líquidos somam R$ 586.213,20 e
R$ 2.204.879,10, respectivamente. Esses valores não pertencem a cabeçalhos de
pedido existentes; somá-los ao faturamento inventaria uma ligação.

**Alternativas consideradas.** (1) Descartar os itens: simplifica a carga, mas
apaga registros e impede investigar o problema. (2) Criar pedidos sintéticos:
preserva os itens no fato, mas exige inventar cliente, data, canal e status.
(3) Separar os itens em quarentena e carregar apenas aqueles com pedido real:
preserva a evidência sem comprometer o grão e as chaves estrangeiras.

**Decisão e justificativa.** Adotamos a alternativa 3. `aud.itens_quarentena`
contém a linha conformada, os IDs originais, o sistema e o motivo
`PEDIDO_INEXISTENTE`. Os 1.371.876 itens restantes entram no fato. A partição é
feita por existência do pedido, e não por eliminação arbitrária de duplicatas.

**O que se perde.** Os órfãos não participam das consultas usuais ao fato de
itens. Não é possível atribuir suas quantidades e valores a clientes, datas ou
pedidos verdadeiros. Os registros permanecem recuperáveis na quarentena e na
origem; o vínculo ausente não pode ser reconstruído com os dados disponíveis.

**Registros afetados.** 20.577/1.392.453 itens (1,4778%) encaminhados à quarentena;
1.371.876/1.392.453 (98,5222%) carregados no fato.

**Asserções associadas.** `particao itens sem perda nem sobreposicao`,
`quarentena apenas pedidos inexistentes`, `itens carregados mais quarentena
LEGADO/ECOM` e integridade das FKs do fato de itens. Cada item deve estar em
exatamente um dos dois destinos, com contagem conferida por sistema.

---

## RDT-11 — Grão dos fatos e prevenção de multiplicação

**Etapa:** 03, carga de dimensões e fatos.

**Evidência.** Há 410.000 pedidos e 1.371.876 linhas de item elegíveis. Existem
320 pares pedido/produto repetidos, envolvendo 640 linhas (0,0467% dos itens
carregados). Agrupar apenas por pedido e produto colapsaria 320 linhas distintas
(0,0233%). Além disso, juntar pedidos, itens, SAC e avaliações antes de agregar
poderia repetir valores de cabeçalho, principalmente o frete.

**Alternativas consideradas.** (1) Uma tabela ampla, repetindo cabeçalhos em cada
item/atendimento/avaliação: facilita algumas consultas, mas torna os totais não
aditivos e introduz multiplicação. (2) Um fato de item por pedido/produto:
reduz linhas, mas perde a identidade de linhas distintas. (3) Separar os grãos
originais e manter a ligação por chaves substitutas.

**Decisão e justificativa.** Adotamos a alternativa 3, com as declarações:

- Uma linha de `dw.fato_pedido` representa um pedido identificado pelo sistema de origem e pelo ID original.
- Uma linha de `dw.fato_item_pedido` representa uma linha de item de um pedido na origem.
- Uma linha de `dw.fato_atendimento` representa um protocolo de atendimento após remoção de cópias exatas.
- Uma linha de `dw.fato_avaliacao` representa uma avaliação identificada por `review_id`.

`aud.map_item` associa cada ID original de item a `item_sk`, `pedido_sk` e
`produto_sk`. `aud.pedidos` conserva IDs e indicadores de conformação. A carga
usa ordenação determinística para gerar chaves. `qtd_itens` significa soma das
**unidades**, não quantidade de linhas. `valor_mercadoria` é o valor bruto dos
itens; `valor_desconto` é o desconto efetivo; `valor_total` inclui o frete uma
única vez. `valor_linha` é quantidade × valor unitário − desconto.

**O que se perde.** O esquema estrela não expõe todos os campos brutos em cada
fato. Por exemplo, o DDL do item não tem ID original: é necessário consultar o
mapa auxiliar. As cópias exatas do SAC já haviam sido reduzidas na RDT-16 da
semana 2 (1.140/96.140 linhas, 1,1858%). Não há colapso adicional das linhas
legítimas de item, nem mudança de valores monetários nesta decisão.

**Registros afetados.** A regra de grão abrange 410.000/410.000 pedidos,
1.371.876/1.371.876 itens elegíveis, 95.000/95.000 protocolos e 160.000/160.000
avaliações (100% de cada população). Preserva especialmente as 640 linhas de
produto repetido identificadas acima.

**Asserções associadas.** `cardinalidade fato_pedido/atendimento/avaliacao`,
`rastro de todas as linhas de item`, `reconciliacao itens por pedido`,
`identidade financeira por pedido`, unicidade garantida por PK/índices e
comparação integral de chaves, valores e restrições após reexecução.

---

## RDT-12 — Pedidos sem cliente correspondente

**Etapa:** 03, verificação anterior à publicação da carga.

**Evidência.** Os 130.000 pedidos legados e os 280.000 digitais encontram
`cliente_sk` após a conformação. São zero pedidos sem cliente em 410.000
(0%). Isso depende de usar o mapa completo de IDs da etapa 2, incluindo os IDs
que foram unificados; não basta ligar somente aos IDs canônicos da dimensão.

**Alternativas consideradas.** (1) Criar um cliente `DESCONHECIDO` e direcionar
órfãos a ele: preserva o pedido, mas mistura pessoas sem identidade conhecida.
(2) Descartar pedidos sem cliente: mantém as FKs válidas, mas perde receita e
população. (3) Exigir mapeamento completo e interromper a carga se aparecer um
caso não resolvido, preservando o estado publicado.

**Decisão e justificativa.** Adotamos a alternativa 3, pois não há casos que
justifiquem criar uma entidade sintética. A verificação ocorre antes de esvaziar
os fatos. Uma falha exige investigação e decisão registrada, não descarte
silencioso ou atribuição automática a outra pessoa.

**O que se perde.** Nenhum pedido é perdido na base atual. A política sacrifica
a disponibilidade de uma nova carga se surgirem órfãos: o processamento é
bloqueado até resolver a referência. Também não recupera identidades reais que
a própria origem não permita distinguir; continuam valendo as limitações de
pareamento por CPF registradas na semana 2.

**Registros afetados.** 0/410.000 pedidos (0%) exigiram tratamento de identidade
na carga; 410.000/410.000 (100%) foram verificados e carregados com cliente válido.

**Asserções associadas.** `pedidos sem cliente correspondente` e
`FK dw.fato_pedido.cliente_sk`. Um teste transacional introduziu um cliente nulo
em um pedido conformado, confirmou o bloqueio e a preservação dos 410.000 fatos,
e reverteu a alteração. O teste é reproduzível em `testar_semana3.py`.

---

## RDT-13 — Vínculos dos arquivos e limites de interpretação

**Etapas:** 02/03, associação do SAC e das avaliações aos pedidos; uso na ABT.

**Evidência.** Todos os 95.000 protocolos únicos e todas as 160.000 avaliações
encontram o pedido declarado; todas as avaliações também encontram o produto
separadamente. Assim, há zero casos sem pedido em cada fonte (0%). Contudo:

- 159.920/160.000 avaliações (99,95%) referenciam produto que não consta nas linhas daquele pedido. Somente 80 pares são consistentes.
- 86.954/95.000 protocolos (91,5305%) têm CPF comparável e diferente do CPF do cliente do pedido. O ID do pedido não comprova quem abriu o contato.
- Em outros 8.045/95.000 protocolos (8,4684%), a comparação de CPF é desconhecida; apenas um protocolo tem igualdade confirmada (0,0011%).
- 47.667/95.000 atendimentos (50,1758%) e 79.777/160.000 avaliações (49,8606%) têm data anterior ao pedido referenciado. As datas não foram deslocadas para forçar coerência.

Essas ocorrências se sobrepõem; seus percentuais não devem ser somados.
Encontrar duas chaves válidas separadamente não prova que a relação entre elas
seja verdadeira. A elevada inconsistência limita o uso analítico dos arquivos.

**Alternativas consideradas.** (1) Excluir registros inconsistentes: evita
relações duvidosas nas consultas, mas elimina quase todas as avaliações.
(2) Manter todos os vínculos sem indicadores: preserva volume, mas dá aparência
de certeza a associações que os dados contradizem. (3) Preservar referências
declaradas e evidência da inconsistência no DW/auditoria, restringindo seu uso
na ABT. Para um ID realmente inexistente, manter a ocorrência com FK nula e
referência original na auditoria; não inventar um pedido.

**Decisão e justificativa.** Adotamos a alternativa 3. As tabelas
`aud.atendimentos` e `aud.avaliacoes` preservam IDs, linha de origem e indicadores
de vínculo ausente; avaliações também têm `produto_consta_no_pedido`. O cliente
do SAC é o proprietário do pedido referenciado, não a identidade comprovada do
solicitante. `compra_verificada` conserva a declaração da fonte, sem ser usada
como validação própria do par pedido/produto.

Na ABT, contatos são contados como **ocorrências associadas aos pedidos do
cliente**, apenas quando a abertura está entre a data do pedido e o corte.
Avaliações exigem, adicionalmente, produto presente no pedido e submissão nesse
mesmo intervalo. Isso resulta em 33.015 atendimentos (34,7526% dos 95.000) e
26 avaliações (0,0163% das 160.000) elegíveis aos atributos. Esses filtros
consideram corte e coerência conjuntamente; não são contagens de registros
apagados do DW. As médias de nota desconhecidas permanecem nulas.

**O que se perde.** Os fatos não resolvem quem realmente escreveu a avaliação
ou abriu o atendimento. A ABT deixa de usar informação potencialmente útil de
registros incoerentes e posteriores ao corte, e sua variável de avaliações fica
quase inteiramente ausente. Preservar a ocorrência no DW mantém a possibilidade
de investigação; não transforma a referência declarada em evidência de compra.
A política para FKs nulas é defensiva: a base atual não contém esses casos e a
etapa 2 também possui verificações que bloqueiam vínculos não encontrados.

**Registros afetados.** Política de preservação aplicada a 255.000/255.000
ocorrências conformadas (100%). Zero ocorrências tiveram FK de pedido anulada;
159.920/160.000 avaliações (99,95%) foram sinalizadas pelo par inconsistente.
Os demais subconjuntos e denominadores estão explicitados acima.

**Asserções associadas.** `vinculos e flags das avaliacoes`,
`SAC sem vinculos fabricados`, cardinalidade dos dois fatos, todas as FKs dos
arquivos e `atributos SAC recalculados ate corte` / `avaliacoes validas
recalculadas ate corte`. A consistência produto/pedido é recalculada a partir
dos itens efetivamente carregados.

---

## RDT-14 — Desenho dos atributos da ABT e corte temporal

**Etapa:** `04_abt.py --correta`.

**Evidência.** A população contém 110.195 clientes com ao menos um pedido registrado até 30/06/2025. Os 410.000 pedidos do DW abrangem 01/01/2023 a 30/12/2025; 68.406 (16,68%) são posteriores ao corte. Agregá-los sem filtro incorporaria informação futura aos preditores. O alvo possui 24.056 positivos (21,83%) entre os clientes elegíveis.

**Alternativas.** (1) Agregar todo o histórico disponível: descreve a fotografia atual, mas é incompatível com uma previsão feita no corte histórico. (2) Restringir os eventos dos preditores ao corte e reservar a janela seguinte para o alvo: adotada. (3) Usar apenas clientes com cadastro completo: simplifica o tratamento de ausências, mas reduz a população sem resolver o vazamento temporal.

**Decisão e justificativa.** A ABT tem uma linha por cliente em 30/06/2025. O alvo é 1 quando existe pedido não cancelado entre 01/07/2025 e 28/09/2025; caso contrário, 0. Recusa de pagamento permanece em CANCELADO. Os nove preditores são:

| Atributo | Regra |
|---|---|
| `recencia_dias` | Dias entre o corte e o último pedido registrado até o corte |
| `frequencia_pedidos` | Quantidade de pedidos registrados até o corte |
| `valor_monetario_total` | Soma dos valores desses pedidos, com frete |
| `ticket_medio` | Média dos valores desses pedidos |
| `tempo_como_cliente` | Dias entre o primeiro pedido registrado e o corte |
| `qtd_atendimentos_sac` | Contatos com abertura entre a data do pedido e o corte |
| `qtd_avaliacoes_consistentes` | Avaliações com produto presente no pedido e submissão entre pedido e corte |
| `nota_media_avaliacoes` | Média das notas disponíveis das avaliações elegíveis |
| `sem_nota_avaliacao` | Indicador de média de avaliação desconhecida |

As medidas de pedidos incluem cancelados e descrevem pedidos registrados, sem usar o status atual como preditor: a fonte não conserva seu histórico de alterações. Cada fonte é agregada por cliente antes das junções. Contagens ausentes recebem zero; média desconhecida permanece NULL com indicador. As datas seguem o dia de negócio da RDT-09. O contrato de tipos, PK, FK e domínio do alvo é preservado.

**O que se perde.** Eventos posteriores ao corte ficam fora dos preditores, mas permanecem no DW. Os filtros de coerência reduzem o aproveitamento dos arquivos: 33.015 atendimentos e 26 avaliações participam dos atributos. Há 110.170 clientes sem média de nota (99,98% da ABT). A ausência de histórico de alterações nas fontes impede comprovar retrospectivamente a disponibilidade de todos os valores e pareamentos; o filtro controla as datas dos eventos, sem eliminar essa limitação.

**Registros afetados.** 110.195/110.195 clientes elegíveis (100%). Os 68.406 pedidos posteriores ao corte ficam excluídos dos preditores; 24.056/110.195 clientes têm alvo 1 (21,83%).

**Asserções associadas.** `populacao elegivel completa`, `ABT grao cliente e corte`, `ABT corte e alvo binario`, `alvo confere com janela e status`, `atributos pedidos recalculados ate corte`, `atributos SAC recalculados ate corte`, `avaliacoes validas recalculadas ate corte` e `atributos invariantes a alteracoes no futuro`. O teste transacional altera eventos futuros e verifica que o hash dos preditores de todos os clientes permanece igual.

---

## RDT-15 — Vazamentos introduzidos deliberadamente na versão de comparação

**Etapa:** `04_abt.py --vazamento`.

**Evidência.** O experimento registrado compara as mesmas 110.195 identidades e o mesmo alvo. Na versão correta, as AUCs dos três modelos ficam entre 0,5267 e 0,5359. A versão contaminada contém 47.984 clientes com recência negativa e a mesma quantidade com frequência maior que na ABT correta, evidenciando o uso de pedidos posteriores ao corte.

**Alternativas.** (1) Inserir o próprio alvo como preditor: demonstra contaminação direta, mas não reproduz os erros de preparação especificados no projeto. (2) Retirar o filtro temporal de recência e frequência e normalizar globalmente uma variável antes da partição: adotada para representar vazamento temporal e de pré-processamento. (3) Manter somente a versão correta: preserva a validade analítica, mas não permite medir o contraexemplo exigido.

**Decisão e justificativa.** `abt.recompra_90d_vazamento` mantém a população e o alvo da ABT correta. Recência e frequência usam todos os pedidos, inclusive posteriores ao corte. `valor_monetario_total` é substituído por `(valor - media_global) / desvio_global`, calculado sobre os clientes elegíveis antes da partição de treino e teste. A soma monetária usada nessa normalização respeita o corte; o erro sutil consiste no acesso às estatísticas dos clientes de teste. Os demais preditores conservam as regras da versão correta. A versão é um controle experimental, sem validade para representar uma previsão feita em 30/06/2025.

**O que se perde.** A avaliação contaminada deixa de estimar o desempenho de uma previsão com informações disponíveis no corte. O nome `valor_monetario_total` conserva-se para comparar os mesmos campos entre versões, mas nessa tabela representa um Z-score, não reais. A interpretação monetária exige consultar a ABT correta. Ausência de grande efeito numérico da normalização não torna o procedimento válido.

**Registros afetados.** 110.195/110.195 clientes (100%) recebem a transformação global. Em 47.984/110.195 (43,54%), a recência fica negativa e a frequência é inflada por pedidos futuros. A população e os 24.056 positivos são preservados.

**Asserções associadas.** `populacao elegivel completa vazamento`, `ABT vazamento grao cliente e corte`, `ABT vazamento corte e alvo binario`, `taxa do alvo vazamento`, `vazamento temporal recencias negativas detectadas`, `vazamento temporal frequencias infladas`, `vazamento sutil media zscore global` e `vazamento sutil desvio zscore global`. As duas últimas verificam média próxima de zero e desvio próximo de um na coluna transformada.

---

## RDT-16 — Duplicatas exatas do SAC

**Etapa:** `transformacoes_semana2.liga_sac_e_avaliacoes`.

**Evidência.** 96.140 linhas possuem 95.000 protocolos distintos. As 1.140 excedentes têm conteúdo idêntico; não há protocolo repetido com conteúdo conflitante.

**Alternativas.** (1) Cada linha como atendimento: preserva multiplicidade, duplica métricas. (2) Escolher arbitrariamente uma linha de qualquer protocolo repetido: permite chave única, pode ocultar conflitos. (3) Remover apenas duplicatas comprovadamente exatas e interromper caso haja conflito: adotada.

**Decisão e justificativa.** Stg mantém todas as linhas. Na conformação, escolhe-se a primeira ocorrência lógica somente após verificar igualdade de todos os campos originais. `_linha_origem` mantém referência ao arquivo, e a chave primária por protocolo assegura o grão de um atendimento.

**O que se perde.** A multiplicidade do arquivo deixa de representar contatos adicionais na visão conformada. Ocorrências e contagens continuam no bruto; não há evidência de atendimentos distintos nas cópias idênticas.

**Registros afetados.** 1.140 linhas redundantes (1,19% das 96.140), resultando em 95.000 eventos únicos. Percentuais posteriores de notas, horas e encerramento usam essa base.

**Asserções associadas.** `SAC protocolos repetidos sem conflito de conteudo` e `SAC uma linha por protocolo`.

---

## RDT-17 — Preços de referência com magnitude suspeita

**Etapa:** `transformacoes_semana2.conforma_categorias`.

**Evidência.** A regra de triagem `preco_referencia > 10 × mediana positiva da origem e categoria_nivel1` sinaliza 8/15.000 produtos (0,05%). Isso não representa todos os erros possíveis nem comprova que esses preços estejam incorretos.

**Alternativas.** (1) Dividir preços extremos por dez: pode corrigir digitação, mas também alterar produtos caros legítimos. (2) Excluir produtos/itens: perde transações e pode romper reconciliação. (3) Preservar preços e vendas, sinalizando suspeita e mediana de referência: adotada por falta de confirmação externa do erro.

**Decisão e justificativa.** `cfm.produtos_auditoria` guarda mediana e `preco_suspeito`; nenhum preço de catálogo nem de venda é substituído. A regra é heurística de investigação, não validação automática.

**O que se perde.** Possíveis erros permanecem nas medidas observadas. Evita-se inventar valores corretos, mas é necessária análise de sensibilidade futura antes de usar extremos em modelos.

**Registros afetados.** 15.000 produtos examinados (100%); oito sinalizados (0,05%); zero preços alterados.

**Asserção associada.** `preco referencia preservado inclusive suspeitos`.

---

## Tabela-resumo das decisões de transformação

Os percentuais usam o denominador indicado em cada linha. Populações de clientes, produtos, pedidos e itens não são intercambiáveis. As fichas detalham os subconjuntos que se sobrepõem.

| Ficha | Decisão | População e percentual | Perda ou limitação |
|---|---|---|---|
| RDT-01 | Carga completa fiel em lotes | 2.205.864 registros (100% das fontes) | Sem histórico de fotografias anteriores em staging |
| RDT-02 | Identidade por CPF exato normalizado | 132.250 cadastros processados (100%); 118.215 identidades resultantes | Fragmentação sem CPF comum e risco de colisão; sobreposição real não quantificável |
| RDT-03 | Deduplicação com mapa de todos os IDs | Legado: 1.427/47.250 (3,02%); digital: 3/85.000 (0,0035%) | Atributos secundários fora da dimensão; aliases e originais preservados |
| RDT-04 | Macrostatus e motivo secundário | 410.000 pedidos (100%); 52.177 cancelados/recusados (12,73%) | Motivo desconhecido no legado; distinção digital preservada |
| RDT-05 | Mercadoria bruta, desconto, frete e total conformados | 410.000 pedidos (100%); total digital com frete em 280.000 | Leitura do total exige definição comum; valor de origem preservado |
| RDT-06 | Desconto sentinela e preservação do frete | 4.056/397.086 itens legados (1,02%); frete negativo em 1.174/410.000 pedidos (0,29%) | Desconto real e causa do frete negativo desconhecidos |
| RDT-07 | Categorias e atividade conformadas | 15.000 produtos (100%); híbridos: 223/3.000 legados (7,43%) | Perda de especificidade dos rótulos híbridos e genéricos |
| RDT-08 | Ausências e inválidos por campo | Denominadores na ficha; entrega sentinela: 1.025/130.000 (0,79%) | Valores reais não recuperáveis; causas distinguíveis preservadas por indicadores |
| RDT-09 | Instantes com fuso e dia de negócio local | 410.000 pedidos e 160.000 avaliações (100% de cada base) | Fuso assumido em 130.000 pedidos legados e 31.915 avaliações sem offset |
| RDT-10 | Quarentena de itens sem pedido | 20.577/1.392.453 itens (1,48%) | Órfãos fora das análises usuais; vínculo não recuperável |
| RDT-11 | Grãos separados com rastreabilidade | 410.000 pedidos, 1.371.876 itens, 95.000 atendimentos e 160.000 avaliações (100% de cada fato) | Campos brutos exigem consulta à auditoria ou origem |
| RDT-12 | Bloqueio de carga se faltar cliente | 0/410.000 pedidos sem cliente (0%); todos verificados | Nova carga bloqueada até investigação de eventual órfão |
| RDT-13 | Preservação dos arquivos e uso analítico restrito | 255.000 ocorrências preservadas (100%); pares inconsistentes em 159.920/160.000 avaliações (99,95%) | Autoria e compra não comprovadas; restrições adicionais na ABT |
| RDT-14 | ABT correta com corte em 30/06/2025 | 110.195 clientes elegíveis (100%); 24.056 positivos (21,83%) | Eventos posteriores excluídos dos preditores; histórico de alterações indisponível |
| RDT-15 | Vazamento temporal e Z-score global | 110.195 clientes (100%); recência negativa e frequência inflada em 47.984 (43,54%) | Métricas contaminadas não representam previsão válida no corte |
| RDT-16 | Remoção apenas das cópias exatas do SAC | 1.140/96.140 linhas excedentes (1,19%); 95.000 protocolos resultantes | Multiplicidade removida da visão conformada; bruto preservado |
| RDT-17 | Sinalização de preços suspeitos sem correção | 15.000 produtos examinados (100%); 8/15.000 sinalizados (0,05%) | Heurística não comprova erro; preços originais preservados |

---

## Reflexão final

### 1. Decisão de maior impacto e evidência experimental

A comparação entre RDT-14 e RDT-15 mostra o impacto da preparação temporal: a AUC da Árvore passa de 0,5267 na base correta para 0,9663 na versão com vazamento temporal e normalização global. No Naive Bayes, passa de 0,5359 para 0,8883. São resultados medidos do experimento completo. O ensaio isolado da normalização apresentou variação pequena; os resultados não autorizam atribuir todo o ganho a ela.

Entre as regras de negócio, a definição de recompra na RDT-04 pode alterar o alvo. Recusas de pagamento são excluídas dos positivos. Não há medição registrada que sustente uma taxa alternativa de recompra nem uma comparação entre modelos sob essa mudança; seu impacto permanece uma hipótese.

### 2. Consequências possíveis sobre pessoas

O pareamento por CPF da RDT-02 pode fragmentar uma pessoa sem CPF comum entre sistemas ou unir pessoas por identificador incorreto. Em uma aplicação real, isso poderia subestimar ou combinar históricos e afetar a seleção para campanhas de retenção. São riscos possíveis, não danos observados neste laboratório. As fontes permitem medir 12.605 CPFs compartilhados, mas não determinar quantas pessoas reais permaneceram fragmentadas. Por isso, não atribuímos um percentual à sobreposição não recuperada.

### 3. Informação ausente que seria necessária

Seriam úteis um identificador de pessoa validado entre os sistemas, o histórico de alterações de cadastro e status, a confirmação dos fusos sem offset e a explicação dos descontos sentinela e fretes negativos. Também faltam vínculos confiáveis entre avaliações, produtos e pedidos. Essas informações permitiriam validar os pareamentos, reconstruir o estado conhecido no corte e distinguir desconhecimento de evento não ocorrido. Preservar originais e indicadores mantém a possibilidade de investigação, mas não recupera informação que a fonte não fornece.
