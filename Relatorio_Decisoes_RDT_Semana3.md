# Registro de Decisões de Transformação — Semana 3

**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi.

**Projeto:** ETL Mercatto — Mineração de Dados, Engenharia da Computação, IFMT.

**Escopo:** carga do esquema estrela, ABT correta, asserções e fichas RDT-10 a RDT-13.

As decisões das fichas 01–09 permanecem em `Relatorio_Decisoes_RDT_Semana2.md`.
Este documento complementa aquela entrega e consolida a RDT-13 na carga efetiva.
As fontes não foram corrigidas. O gerador, `config.py`, o DDL fornecido e o
framework de asserções foram preservados. A implementação abrange as etapas
3 e 4 e os utilitários de auditoria e validação.

## 1. Resultado da carga

| Tabela | Registros |
|---|---:|
| `dw.dim_cliente` | 118.215 |
| `dw.dim_produto` | 15.000 |
| `dw.dim_status` | 9 |
| `dw.dim_tempo` | 1.217 |
| `dw.dim_canal` | 6 |
| `dw.fato_pedido` | 410.000 |
| `dw.fato_item_pedido` | 1.371.876 |
| `dw.fato_atendimento` | 95.000 |
| `dw.fato_avaliacao` | 160.000 |
| `aud.itens_quarentena` | 20.577 |
| `abt.recompra_90d` | 110.195 |

As dimensões de tempo e canal também foram populadas. `stg` mantém a extração
fiel; `cfm` mantém a conformação da semana 2; `aud` preserva a rastreabilidade,
a quarentena e as limitações dos vínculos usados no DW. A etapa 3 reutiliza as
chaves de cliente, produto e status construídas na etapa 2.

## 2. Ficha RDT-10 — Itens sem pedido correspondente

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

## 3. Ficha RDT-11 — Grão dos fatos e prevenção de multiplicação

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

## 4. Ficha RDT-12 — Pedidos sem cliente correspondente

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

## 5. Ficha RDT-13 — Vínculos dos arquivos e limites de interpretação

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

## 6. Reconciliação financeira exigida na semana

A referência é consultada **diretamente** nas origens com os usuários `etl_ro`,
e não apenas em uma tabela intermediária. Como o total conformado inclui frete,
a comparação respeita a diferença de significado identificada na RDT-05.

| Sistema | Referência direta | Total na origem (R$) | Total no DW (R$) | Desvio |
|---|---|---:|---:|---:|
| Legado | `SUM(PEDIDOS.VALOR_TOTAL)` | 281.084.957,13 | 281.084.957,13 | 0,0000% |
| E-commerce | `SUM(shop.orders.total_amount + freight_amount)` | 745.850.860,33 | 745.850.860,33 | 0,0000% |

O limite é `abs(total_dw − total_origem) / abs(total_origem) <= 0,001` (0,1%).
Quando a referência é zero, exige-se igualdade exata. O total digital sem frete,
R$ 734.859.099,95, não é diretamente comparável ao total com frete do DW.

Também são conferidos, para cada pedido, unidades, mercadoria bruta, descontos e
valor líquido dos itens, além da identidade
`valor_total = valor_mercadoria + valor_frete − valor_desconto`.
Os registros de reconciliação ficam em `aud.reconciliacao` e as asserções em
`qa.execucao_assercao`. O resultado não prova que descontos originalmente
ignorados fossem realmente zero; essa limitação da sentinela `-1` permanece
documentada na RDT-06.

## 7. ABT correta: população, atributos e corte temporal

O contrato foi preservado: `cliente_sk BIGINT`, `data_corte DATE`,
`alvo_recompra_90d SMALLINT`, chave primária `(cliente_sk, data_corte)`, FK de
cliente e restrição de alvo binário. A carga acrescenta colunas e insere linhas
sem substituir a tabela por `to_sql(...replace)`.

A população tem ao menos um pedido registrado até **30/06/2025**, inclusive
cancelados, conforme a definição de população do contrato analítico. São 110.195
clientes. O alvo é 1 se existe pedido entre **01/07/2025 e 28/09/2025**, com
status conformado diferente de `CANCELADO`; caso contrário, 0. Foram encontrados
24.056 positivos (21,8304%). Recusa de pagamento permanece em `CANCELADO`.

| Atributo | Definição até o corte |
|---|---|
| `recencia_dias` | Dias desde o último pedido registrado |
| `frequencia_pedidos` | Número de pedidos registrados, incluindo cancelados |
| `valor_monetario_total` | Soma dos valores desses pedidos, com frete |
| `ticket_medio` | Média dos valores desses pedidos |
| `tempo_como_cliente` | Dias desde o primeiro pedido registrado |
| `qtd_atendimentos_sac` | Contatos associados a pedidos, com abertura entre pedido e corte |
| `qtd_avaliacoes_consistentes` | Avaliações com par produto/pedido válido e submissão entre pedido e corte |
| `nota_media_avaliacoes` | Média das notas disponíveis das avaliações elegíveis |
| `sem_nota_avaliacao` | Indica média de avaliação desconhecida |

As cinco primeiras variáveis descrevem **pedidos registrados**, e não receita
reconhecida ou compras concluídas. Não filtramos essas variáveis pelo status
atual, porque a origem não informa o histórico de mudanças de status. Também
não usamos data de entrega, resolução, votos úteis ou atributos cadastrais
atualizados como preditores. O status é usado somente na definição do alvo.

Cada fonte é agregada por cliente antes das junções. Contagem ausente vira zero;
nota desconhecida permanece `NULL`, acompanhada de indicador. Há 110.170
clientes sem nota (99,9773% da ABT). Não foi aplicada normalização nem imputação
pela média. Qualquer preparação estatística para modelagem deve ser ajustada
exclusivamente sobre o conjunto de treinamento.

A ABT utiliza as datas locais de negócio da RDT-09, com hipótese de fuso
`America/Sao_Paulo` para timestamps sem zona. Os valores dos pedidos são tratados
como dados do evento registrado. A origem não oferece histórico de alterações
ou de identidades; portanto, a regra controla datas dos eventos, mas não prova
retrospectivamente que todos os valores e pareamentos já estavam disponíveis
naquele dia. Essa limitação não pode ser eliminada por um filtro SQL.

As verificações recalculam todos os atributos com o corte e o alvo com sua
janela. Um teste modifica, dentro de uma transação revertida, 68.406 pedidos,
26.736 avaliações e 15.721 atendimentos posteriores ao corte. O hash de **todos
os atributos de todos os clientes** permanece idêntico. A alteração do futuro
pode legitimamente alterar o alvo; o teste compara apenas os preditores.

## 8. Qualidade, reprodução e entrega

A etapa 3 e a ABT são transacionais: asserção reprovada ou exceção impede a
publicação parcial. Reexecutar a etapa 3 invalida a ABT anterior; deve-se executar
a etapa 4 em seguida. A etapa 2 mantém sua proteção contra reprocessar dimensões
sobre fatos já carregados.

As validações e instruções estão em `lab-etl-varejo/docs/SEMANA3_EXECUCAO.md`.
Os resultados completos, incluindo contagens, hashes e verificações de restauração,
acompanham o pacote em `validacao/`. O dump inclui `dw`, `abt`, `aud` e o histórico
`qa`; o código permite reconstruir `stg` e `cfm` a partir das fontes determinísticas.
Falhas de desenvolvimento permanecem no histórico: a aprovação deve ser verificada
pela última execução de cada etapa, não pela inexistência de qualquer falha antiga.

| Validação concluída | Asserções aprovadas | Falhas |
|---|---:|---:|
| Extração na cadeia em destino vazio | 27 | 0 |
| Transformação na cadeia em destino vazio | 40 | 0 |
| Carga do DW | 35 | 0 |
| ABT correta | 12 | 0 |
| Testes de futuro e bloqueio por cliente ausente | 6 | 0 |
| Reexecução das etapas 3 e 4 | 66 | 0 |
| Comparação da cadeia 1–4 com a referência | 66 | 0 |
| Restauração do dump, incluindo histórico QA | 70 | 0 |

As comparações verificam 16 tabelas de DW, ABT e auditoria; a restauração inclui
também `qa.execucao_assercao`, totalizando 17. Além das contagens, conferem o
conteúdo integral por SHA-256, tipos, restrições e sequências. O teste da cadeia
recriou o destino desde o DDL vazio e reutilizou as fontes determinísticas
existentes; não foi necessário recriar os bancos de origem.

| Ficha | Decisão | População afetada | Perda/limitação principal |
|---|---|---|---|
| 10 | Quarentena dos itens sem pedido | 20.577/1.392.453 (1,4778%) | Órfãos fora das análises usuais de itens; vínculo não recuperável |
| 11 | Pedido e linha de item em grãos separados | 100% dos fatos; 640 linhas repetem par pedido/produto | Campos brutos exigem consulta à auditoria/origem |
| 12 | Bloqueio se faltar cliente | 0/410.000 casos (0%); todos verificados | Nova carga pode ficar indisponível até investigar |
| 13 | Preservar referências e sinalizar inconsistências | 255.000 ocorrências (100%); 159.920 avaliações inconsistentes (99,95%) | Autoria e compra não comprovadas; forte redução do uso na ABT |

**Referências:** `Projeto_Pratico_ETL_Mercatto.pdf`, seções 3.3, 4, 6 e 7;
`docs/MODELO_RDT.md`; DDL do DW; decisões e resultados medidos das semanas 2 e 3.
