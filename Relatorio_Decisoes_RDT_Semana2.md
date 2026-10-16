# Registro de Decisões de Transformação — Semana 2

**Mineração de Dados · IFMT · Entrega 2**

**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi

**Ambiente:** Docker, escala 1,0, semente 20262

**Versão do pipeline:** 0.2.1

## Escopo e evidências

Esta entrega contém as fichas RDT-01 a RDT-09 e as etapas executáveis `01_extracao.py` e `02_transformacao.py`. A ligação dos arquivos aos pedidos, também exigida na Semana 2, é registrada na ficha antecipada RDT-13. As fichas adicionais RDT-16 e RDT-17 tratam duplicatas do SAC e preços suspeitos. As fichas de carga dos fatos e modelagem serão completadas nas semanas seguintes.

As contagens foram medidas nas fontes completas. Valores de geração não foram usados como prova de identidade real de clientes nem como substituição de medição. Os resultados estão em `saida/semana2_resultados.json`; o inventário de ausências também está em `cfm.inventario_ausencias`.

A extração escreve somente no destino, usando `etl_ro` nas origens. `stg` contém as cópias integrais; o esquema adicional `cfm` contém dados conformados, indicadores e mapeamentos. As dimensões de cliente, produto e status são preparadas para a carga posterior. Os fatos e a ABT não são carregados nesta entrega. `config.py`, o gerador, os DDLs fornecidos e o framework de asserções foram preservados.

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

## RDT-03 — Duplicatas internas e mapeamento de todos os IDs

**Etapa:** `transformacoes_semana2.unifica_clientes`.

**Evidência.** A normalização encontra 1.427 registros excedentes por CPF no legado e três no e-commerce. Os três IDs digitais excedentes são referenciados por 14 pedidos. Duplicação por CPF e duplicação por nome não são tratadas como o mesmo problema.

**Alternativas.** (1) Excluir excedentes sem mapeamento: simplifica a dimensão, mas deixa pedidos sem destino para seus IDs. (2) Deduplicar registros sem CPF por similaridade: recupera possíveis duplicatas com risco de fusão não validado. (3) Eleger menor ID por CPF dentro de cada origem e preservar todos os aliases: adotada.

**Decisão e justificativa.** Todos os IDs ficam em `cfm.clientes_origem` e nos mapas `cfm.map_cliente_legado` e `cfm.map_cliente_ecom`, inclusive duplicatas e ausências. Nos atributos da identidade unificada, prioriza-se o cadastro canônico digital quando existe; cidade disponível pode vir do legado, e `dt_primeiro_cadastro` usa a menor data registrada no grupo. Nomes são normalizados; cidade `N/A` não é tratada como cidade válida.

**O que se perde.** A dimensão apresenta um único conjunto de atributos, suprimindo variações secundárias na visão integrada. Atributos e IDs originais continuam acessíveis em `stg` e nos mapas. Duplicatas sem CPF não são removidas por suposição de identidade.

**Registros afetados.** 1.427 registros colapsados no legado (3,02% de 47.250), resultando em 45.823 identidades dessa origem antes da integração. No e-commerce, três (0,0035% de 85.000) são colapsados. Os mapas preservam 47.250/47.250 IDs legados e 85.000/85.000 digitais (100% em cada origem), cobrindo os 410.000 pedidos.

**Asserções associadas.** `mapa completo clientes legado`, `mapa completo clientes ecommerce`, `pedidos sem mapa de cliente` e verificações de unicidade de CPF. A cobertura não é limitada aos IDs canônicos.

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

## RDT-06 — Desconto sentinela e frete negativo

**Etapa:** `transformacoes_semana2.conforma_valores`.

**Evidência.** 4.056 itens legados (1,02% dos 397.086) contêm desconto `-1`, distribuídos por 4.003 pedidos (3,08% dos 130.000). Subtrair literalmente esse valor adicionaria R$ 1,00 por item. Há frete negativo em 362 pedidos legados (0,28%) e 812 digitais (0,29%), total de 1.174/410.000 (0,29%).

**Alternativas.** (1) Tratar `-1` como desconto real: cria acréscimo incompatível com a reconciliação. (2) Anular desconto e totais desses pedidos: explicita incerteza, mas impede reconciliar medidas disponíveis. (3) Zero efetivo com indicador de ausência: adotada por fechar os cabeçalhos sem afirmar que o desconto real foi zero. Para frete, foram consideradas a exclusão dos pedidos, a substituição por zero e a preservação do sinal; adotou-se preservar.

**Decisão e justificativa.** Somente o sentinela `-1` vira zero efetivo, com `desconto_nao_informado=TRUE`. Outros descontos não são truncados indiscriminadamente. O frete mantém valor e sinal, permitindo reconciliação. Não há evidência suficiente para afirmar que represente crédito, subsídio ou erro: sua causa permanece desconhecida.

**O que se perde.** O desconto real não é recuperável. Uma análise que ignore o indicador confundirá ausência com desconto zero. Preservar fretes negativos pode manter defeitos da origem, mas evita inventar receita ou apagar sua ocorrência.

**Registros afetados.** 4.056 itens (1,02% do legado) recebem desconto efetivo zero e indicador; 1.174 pedidos (0,29% do conjunto) mantêm frete negativo.

**Asserções associadas.** `nenhum desconto sentinela conformado`, `frete preserva valor e sinal da origem` e `reconciliacao por pedido com origem`.

## RDT-07 — Taxonomia de produtos e atributo de atividade

**Etapa:** `transformacoes_semana2.conforma_categorias`.

**Evidência.** Há 27 rótulos distintos para 3.000 produtos legados e 21 nós (8 raízes, 13 filhos) para 12.000 digitais. Os casos híbridos são 112 produtos em `informatica e games` (3,73% do legado) e 111 em `TV E SOM` (3,70%). `DIVERSOS`, `OUTROS` e vazio somam 340 (11,33%). O atributo ATIVO contém 340 valores N (11,33%), que não podem ser convertidos por `bool("N")`.

**Alternativas.** (1) Excluir produtos ambíguos/genéricos: perde catálogo e vínculos dos itens. (2) Inferir categoria específica pela descrição: pode recuperar detalhe, exige validação adicional. (3) Mapear de forma determinística, preservando categoria original e indicadores: adotada.

**Decisão e justificativa.** Adota-se a árvore digital; variantes de grafia são uniformizadas para consultar o mapa. `TV E SOM` fica em `Áudio e TV`, sem subcategoria. `informatica e games` fica em `Informática`, sem subcategoria, como escolha operacional explícita: não é uma correspondência sem perda nem o pai comum dos dois ramos. Genéricos ficam em `Outros`. Rótulos amplos `TELEFONIA` e `AUDIO/VIDEO` não são reduzidos artificialmente a `Smartphones` ou `Áudio`. Preservam-se `categoria_origem` e indicadores de ambiguidade. IDs de produtos entre sistemas não são equiparados. S vira TRUE e N FALSE.

**O que se perde.** A projeção do rótulo híbrido em Informática não representa a participação de games; análises somente pela categoria conformada omitem esse aspecto. Categorias amplas/genéricas não permitem reconstruir subcategorias. O texto original permite auditar a escolha.

**Registros afetados.** 15.000 produtos (100%); 223 híbridos (7,43% dos 3.000 legados), 340 genéricos (11,33%) e 340 inativos legados corretamente preservados (11,33%). Mapas cobrem 3.000 IDs legados e 12.000 digitais (100%).

**Asserções associadas.** `cardinalidade produtos preservada`, `categoria origem preservada`, `sku de produto unico` e `ativo S e N corretamente mapeados`.

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

## RDT-09 — Fusos horários, UTC e dia de negócio

**Etapas:** `conforma_valores`, `trata_datas_e_ausencias` e `liga_sac_e_avaliacoes`.

**Evidência.** O legado usa timestamps sem fuso; o e-commerce fornece instantes TIMESTAMPTZ. No JSON, 31.915/160.000 horários (19,95%) não informam offset. Converter tudo ao dia UTC sem critério muda o dia civil de 44.184/410.000 pedidos (10,78%), sendo 9.290 legados e 34.894 digitais.

**Alternativas.** (1) Ignorar offsets e comparar horários ingênuos: mistura instantes. (2) Assumir Cuiabá para todos os horários sem fuso: defensável com confirmação da operação local, indisponível. (3) Assumir `America/Sao_Paulo` para horários sem fuso, guardar instantes em UTC e conservar o dia de negócio nessa zona: adotada como convenção explícita.

**Decisão e justificativa.** O fuso assumido é hipótese, não descoberta comprovada. Horários legados recebem essa zona; os digitais preservam o instante; avaliações respeitam offset quando disponível, e as demais recebem a hipótese e `fuso_assumido=TRUE`. Usam-se timestamps com fuso. `data_pedido_local`, `data_entrega_local` e data civil de avaliação são derivadas em America/Sao_Paulo. DATA_CORTE continua 30/06/2025: o corte diário deve usar a data local de negócio, sem redefinir silenciosamente o contrato para meia-noite UTC. O SAC informa somente datas e não recebe um horário artificial.

**O que se perde.** O fuso verdadeiro dos horários ingênuos é irrecuperável sem informação externa. A hipótese pode deslocar eventos se a origem operava em outra zona; string/data bruta e indicador tornam o risco auditável. A data diária perde o horário, por isso o timestamp completo também é mantido.

**Registros afetados.** 410.000 pedidos (100%) e 160.000 avaliações (100%) recebem representação uniforme. A hipótese aplica-se a 130.000 horários de pedido legados (100% dessa origem) e 31.915 avaliações (19,95% do JSON). A fronteira de corte também é verificada às 23h59min59s.

**Asserções associadas.** `UTC legado representa horario local assumido`, `UTC ecommerce preserva instante original`, `JSON sem fuso recebe zona assumida`, `JSON com fuso preserva instante` e `fronteira do corte em horario de negocio`.

## RDT-13 — Ligação dos arquivos aos pedidos e produtos (antecipação)

**Etapa:** `transformacoes_semana2.liga_sac_e_avaliacoes`. Cobre a sexta decisão obrigatória da Semana 2; povoamento dos fatos fica para a Semana 3.

**Evidência.** Todas as 96.140 linhas brutas do SAC encontram pedido pela chave composta e têm CPF preenchido. As 5.985 linhas (6,23%) sem correspondência de CPF nos cadastros não são documentos omitidos. Todas as 160.000 avaliações encontram pedido e produto separadamente. Contudo, 159.920 avaliações (99,95%) referenciam produto que não consta nos itens do pedido: existência de ambas as entidades não comprova aquela compra.

**Alternativas.** (1) Vincular SAC ao cliente somente por CPF: perde cobertura ou multiplica registros. (2) Descartar casos sem CPF correspondente e avaliações sem comprovação do par pedido-produto: perde interações observadas. (3) Usar o pedido com origem para vincular o cliente e conservar referências/indicadores de consistência: adotada.

**Decisão e justificativa.** `(origem_sistema,id_pedido_origem)` gera LEG-id ou ECOM-id; avaliações usam `order.ref` e `product.sku`. O cliente associado é o titular do pedido, sem confirmar quem contatou o SAC. O CPF informado é preservado para auditoria. A relação produto-item é sinalizada por `produto_consta_no_pedido`, sem apagar avaliações nem tratá-las automaticamente como compras comprovadas. Uma nova referência sem destino faz a asserção falhar e a conformação reverter, mantendo o bruto para decisão explícita; não há descarte silencioso.

**O que se perde.** Atribuir ao titular não comprova autoria do contato. Avaliações inconsistentes exigem considerar o indicador em análises futuras; o RDT da carga deverá retomar esse limite.

**Registros afetados.** 95.000 protocolos únicos (100% do SAC conformado, após RDT-16) e 160.000 avaliações (100%). Os vínculos não multiplicam eventos.

**Asserções associadas.** `SAC encontra pedido e cliente sem multiplicar`, `avaliacoes encontram pedido e produto` e `avaliacoes cardinalidade preservada`.

## RDT-16 — Duplicatas exatas do SAC

**Etapa:** `transformacoes_semana2.liga_sac_e_avaliacoes`.

**Evidência.** 96.140 linhas possuem 95.000 protocolos distintos. As 1.140 excedentes têm conteúdo idêntico; não há protocolo repetido com conteúdo conflitante.

**Alternativas.** (1) Cada linha como atendimento: preserva multiplicidade, duplica métricas. (2) Escolher arbitrariamente uma linha de qualquer protocolo repetido: permite chave única, pode ocultar conflitos. (3) Remover apenas duplicatas comprovadamente exatas e interromper caso haja conflito: adotada.

**Decisão e justificativa.** Stg mantém todas as linhas. Na conformação, escolhe-se a primeira ocorrência lógica somente após verificar igualdade de todos os campos originais. `_linha_origem` mantém referência ao arquivo, e a chave primária por protocolo assegura o grão de um atendimento.

**O que se perde.** A multiplicidade do arquivo deixa de representar contatos adicionais na visão conformada. Ocorrências e contagens continuam no bruto; não há evidência de atendimentos distintos nas cópias idênticas.

**Registros afetados.** 1.140 linhas redundantes (1,19% das 96.140), resultando em 95.000 eventos únicos. Percentuais posteriores de notas, horas e encerramento usam essa base.

**Asserções associadas.** `SAC protocolos repetidos sem conflito de conteudo` e `SAC uma linha por protocolo`.

## RDT-17 — Preços de referência com magnitude suspeita

**Etapa:** `transformacoes_semana2.conforma_categorias`.

**Evidência.** A regra de triagem `preco_referencia > 10 × mediana positiva da origem e categoria_nivel1` sinaliza 8/15.000 produtos (0,05%). Isso não representa todos os erros possíveis nem comprova que esses preços estejam incorretos.

**Alternativas.** (1) Dividir preços extremos por dez: pode corrigir digitação, mas também alterar produtos caros legítimos. (2) Excluir produtos/itens: perde transações e pode romper reconciliação. (3) Preservar preços e vendas, sinalizando suspeita e mediana de referência: adotada por falta de confirmação externa do erro.

**Decisão e justificativa.** `cfm.produtos_auditoria` guarda mediana e `preco_suspeito`; nenhum preço de catálogo nem de venda é substituído. A regra é heurística de investigação, não validação automática.

**O que se perde.** Possíveis erros permanecem nas medidas observadas. Evita-se inventar valores corretos, mas é necessária análise de sensibilidade futura antes de usar extremos em modelos.

**Registros afetados.** 15.000 produtos examinados (100%); oito sinalizados (0,05%); zero preços alterados.

**Asserção associada.** `preco referencia preservado inclusive suspeitos`.

## Tabela-resumo do RDT parcial

| Ficha | Decisão | Registros afetados e base | Perda ou limite principal |
|---|---|---|---|
| 01 | Carga completa fiel | 2.205.864 (100% da extração) | Sem histórico de fotografias anteriores |
| 02 | Identidade por CPF | 132.250 (100%); 12.605 CPFs compartilhados | Fragmentação e risco de colisão |
| 03 | Deduplicação com aliases | 1.427/47.250 (3,02%); 3/85.000 (0,0035%) | Atributos secundários fora da dimensão |
| 04 | Status hierárquico | 410.000 pedidos (100%) | Motivo desconhecido no legado |
| 05 | Medidas monetárias comuns | 410.000 pedidos (100%) | Total depende da definição de origem |
| 06 | Sentinela e frete negativo | 4.056/397.086 itens (1,02%); 1.174/410.000 pedidos (0,29%) | Desconto real e causa desconhecidos |
| 07 | Categorias e atividade | 15.000 produtos (100%); 223/3.000 híbridos (7,43%) | Granularidade do rótulo híbrido |
| 08 | Ausências e inválidos | Bases por campo na ficha; 2.458/410.000 inversões (0,60%) | Valores reais não recuperáveis |
| 09 | UTC com dia local | 410.000 pedidos e 160.000 avaliações (100%) | Fuso real desconhecido |
| 13 | Referências de arquivos | 95.000 protocolos e 160.000 avaliações (100%) | Autoria e compra não comprovadas |
| 16 | Duplicatas SAC | 1.140/96.140 (1,19%) | Multiplicidade removida da visão conformada |
| 17 | Preços suspeitos | 8/15.000 (0,05%) | Possíveis erros preservados com alerta |

## Execução, qualidade e reprodutibilidade

Na pasta `lab-etl-varejo`:

```powershell
docker compose up -d --build
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
```

O Dockerfile instala os requisitos originais e a dependência complementar de autenticação do MySQL, sem modificar `requirements.txt`. A extração é atômica por tabela; a conformação inteira é transacional. Se houver fatos/ABT de semanas posteriores, a etapa 2 interrompe antes de truncar dimensões: usar um destino vazio ou isolado para esta entrega.

**Resultado verificado:** 27 asserções de extração, 40 de transformação e 51 de comparação após reexecutar integralmente as duas etapas, todas aprovadas (118 verificações, zero falhas nas últimas execuções). As 25 tabelas comparadas mantiveram contagens e hashes idênticos. Esse resultado verifica estas etapas; não certifica a carga de fatos e a modelagem ainda não implementadas.

As asserções ficam em `qa.execucao_assercao` e em `saida/semana2_qa_extracao.json` e `semana2_qa_transformacao.json`. Tentativas anteriores em falha permanecem no histórico. Para consultar somente a execução mais recente de cada etapa:

```sql
SELECT q.etapa, COUNT(*) AS assercoes,
       COUNT(*) FILTER (WHERE NOT q.aprovado) AS falhas
FROM qa.execucao_assercao q
WHERE q.etapa IN ('01_extracao','02_transformacao','02_verificacao_reexecucao')
  AND q.executado_em = (
      SELECT MAX(x.executado_em) FROM qa.execucao_assercao x
      WHERE x.etapa = q.etapa)
GROUP BY q.etapa ORDER BY q.etapa;
```

A verificação de reexecução compara contagem e SHA-256 de todas as linhas ordenadas de 25 tabelas: 11 cópias brutas, 11 derivadas e três dimensões. Apenas `_extraido_em`, que muda por definição, é excluído do hash de reexecução. Conteúdo, IDs, indicadores e chaves substitutas devem ser idênticos.

```powershell
docker compose exec -T etl python verificar_semana2.py --gravar-referencia
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
docker compose exec -T etl python verificar_semana2.py --comparar
```

Os comandos produzem `saida/semana2_referencia.json`, `semana2_verificacao.json` e `semana2_qa_reexecucao.json`. A verificação cobre a reexecução integral destas etapas; as etapas 3 a 5 ainda não fazem parte da entrega da Semana 2.

## Referências

Projeto Prático ETL Mercatto, seções 3.2 e 4; referencial ETL da disciplina; `docs/MODELO_RDT.md`; Dicionário de Dados; esquemas SQL e contratos dos esqueletos fornecidos. Código: `01_extracao.py`, `02_transformacao.py`, `transformacoes_semana2.py`, `semana2_utils.py` e `verificar_semana2.py`.
