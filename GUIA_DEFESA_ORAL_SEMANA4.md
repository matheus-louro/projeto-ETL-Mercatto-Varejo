# Roteiro e Guia Estratégico para a Defesa Oral (15 minutos)

**Mineração de Dados · Engenharia de Computação · IFMT — 2026/2**  
**Projeto Prático de ETL — Mercatto Varejo**  
**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi  
**Tempo limite:** 15 minutos por equipe (rigoroso)

---

## 1. Cronograma Sugerido de Apresentação (15 Minutos)

| Bloco | Duração | Conteúdo Principal | Apresentador Sugerido |
|---|:---:|---|---|
| **Bloco 1: Introdução e Arquitetura** | **2 min** | Cenário Mercatto, 4 fontes heterogêneas (2,2 mi registros), fluxo das camadas (`stg` $\to$ `cfm` $\to$ `dw` $\to$ `aud` $\to$ `abt` $\to$ `qa`). | Integrante 1 |
| **Bloco 2: Decisões Centrais de Transformação** | **5 min** | Destaque para as 4 decisões mais densas: RDT-02 (identidade), RDT-05 (semântica do frete), RDT-10 (quarentena de órfãos) e reconciliação financeira (resíduo zero). | Integrante 2 |
| **Bloco 3: O Experimento de Vazamento** | **5 min** | Definição da ABT correta ($t_0 = \text{30/06/2025}$), introdução do vazamento temporal e sutil, e comparação das métricas no Orange/Scikit (AUC saltando de 0,53 para 0,96). | Integrante 1 |
| **Bloco 4: A Pergunta de Ouro & Conclusão** | **3 min** | Como diagnosticar o vazamento às cegas (os 4 testes de auditoria) e resposta à reflexão sobre impacto em pessoas reais. | Integrante 2 / Ambos |

---

## 2. Pontos-Chave e Argumentação Técnica por Bloco

### Bloco 1: Arquitetura e Integridade (2 min)
* **Princípio central:** Não tocamos nas origens (acesso `etl_ro`, somente leitura). Todo o tratamento ocorre no pipeline conteinerizado.
* **Fidelidade da Extração (`stg`):** Ingestão completa em lotes de 10.000, preservando sentinelas, tipos e JSONB original sem manipulação prévia.
* **Reprodutibilidade Determinística:** O pipeline é 100% determinístico (semente `20262`). Qualquer pessoa executa os comandos do zero e obtém o mesmo resultado auditado em `qa.execucao_assercao`.

---

### Bloco 2: As Quatro Decisões Mais Importantes do RDT (5 min)

#### 1. RDT-02 · Unificação de Clientes por CPF (Armadilha do Gabarito)
* **O que falar:** *"O CPF é a única ponte viável entre o ERP legado e o e-commerce. Porém, ~9% dos CPFs possuem dígito verificador inválido em ambos os sistemas. Se filtrássemos apenas CPFs válidos matematicamente, perderíamos cerca de 9% das uniões legítimas de clientes, porque o erro de digitação foi propagado igualmente para as duas plataformas. Tratar validade cadastral como utilidade de identificador seria um erro: o CPF com erro de digitação ainda é um identificador estável e único."*

#### 2. RDT-05 · Semântica Monetária e a Armadilha Silenciosa do Frete
* **O que falar:** *"Descobrimos que `VALOR_TOTAL` no legado inclui frete, enquanto `total_amount` no e-commerce é estritamente o valor líquido dos itens. Reconciliamos os 410.000 pedidos com a soma dos itens: se somássemos diretamente os campos brutos, distorceríamos o faturamento. Harmonizamos para total com frete adicionando `freight_amount` no e-commerce, atingindo uma reconciliação financeira com desvio de R$ 0,00 (0,0000%) nas duas origens, muito além da tolerância de 0,1% exigida."*

#### 3. RDT-10 · Quarentena de Itens Órfãos
* **O que falar:** *"Identificamos 20.577 itens que não encontravam pedidos correspondentes (1,48% em ambas as origens, somando R$ 2,79 mi). Descartá-los apagaria a evidência contábil; inventar pedidos sintéticos violaria o grão e fabricaria clientes. Isolamos esses itens na tabela `aud.itens_quarentena` com o motivo `PEDIDO_INEXISTENTE`, garantindo integridade referencial estrita e zero órfãos no DW."*

#### 4. RDT-11 · Grão Atômico e Prevenção de Multiplicação
* **O que falar:** *"Declaramos o grão atômico de cada tabela-fato. Uma linha de `dw.fato_pedido` é um pedido único; uma linha de `dw.fato_item_pedido` é uma linha de item. Preservamos 640 linhas com pares repetidos de pedido/produto sem agregá-los artificialmente e mantivemos o frete no cabeçalho para evitar multiplicação em junções."*

---

### Bloco 3: O Experimento de Vazamento (5 min)

#### 1. Construção da ABT Correta
* **Corte Temporal:** $t_0 = \text{30/06/2025}$.
* **População:** 110.195 clientes elegíveis (com histórico prévio até $t_0$).
* **Alvo de Recompra:** 1 se recomprou entre 01/07/2025 e 28/09/2025 com status não-cancelado; 0 caso contrário (taxa positiva de **21,83%**; 24.056 clientes).
* **Desempenho Realista:** Modelos legítimos apresentam AUC entre **0,526 e 0,536** no conjunto de teste estratificado (70/30). É um desempenho modesto, mas verdadeiro para variáveis comportamentais em janela curta.

#### 2. Os Dois Vazamentos Introduzidos
1. **Vazamento Temporal Óbvio:** Omissão do corte temporal no cálculo de `recencia_dias` e `frequencia_pedidos`.
   * **Efeito:** A Árvore de Decisão salta de **AUC 0,5267 para 0,9663** e a Acurácia Balanceada de **0,50 para 0,8644**! O Naive Bayes salta de **AUC 0,5359 para 0,8883**!
2. **Vazamento Metodológico Sutil:** Normalização (*Z-score*) global de `valor_monetario_total` antes do split de treino/teste.
   * **Efeito:** Produz variação quase imperceptível nas métricas ($\Delta \text{AUC} \approx -0,0003$). É o vazamento mais perigoso justamente porque não soa alarmes no laboratório, mas quebra a predição em produção ao vazar parâmetros populacionais da distribuição de teste.

---

### Bloco 4: A Pergunta de Ouro da Banca e Resposta Pronta (3 min)

> **Pergunta que o Professor Orlando Júnior fará:**  
> *"Se você tivesse recebido apenas o resultado da versão com vazamento, sem saber como ela foi construída e sem ver o código, como descobriria que ele está errado?"*

**Resposta estruturada em 4 argumentos irrefutáveis:**

1. **A Prova Material no Domínio (Recência Negativa):**  
   *"Inspecionando o sumário estatístico (`describe`) de `recencia_dias`: o valor mínimo é de **-89 dias**. Como a recência é contratualmente $t_0 - \max(t_{\text{compra}})$, uma recência negativa significa matematicamente que o cliente comprou depois da data de corte. Há 47.984 clientes com recência $< 0$ na base, provando que dados do futuro entraram na matriz preditora."*

2. **Hipertrofia de Importância de Atributos:**  
   *"Ao analisar a importância das variáveis na Árvore de Decisão ou nos coeficientes da Regressão Logística, `recencia_dias` absorve **92,1%** de todo o poder explicativo do modelo. Em mineração de dados de varejo, nenhuma variável de comportamento passado tem 92% de importância isolada. Uma concentração desse nível indica que a variável não é preditora, mas sim um proxy da própria variável alvo."*

3. **Validação Fora do Tempo (*Out-of-Time / Backtesting*):**  
   *"Se submetermos esse modelo a um teste cronológico real — aplicando o modelo treinado sobre clientes de um trimestre subsequente —, o desempenho desaba instantaneamente para o nível do acaso ($\approx 50\%$). Isso ocorre porque novos clientes em produção não terão compras futuras já computadas para gerar recências negativas no instante $t_0$."*

4. **Regra de Decisão Determinística Suspeita:**  
   *"No primeiro nó da Árvore de Decisão, o modelo encontra a regra: `Se recência < 0 -> Probabilidade de Recompra = 98%`. Nenhum fenômeno social ou mercadológico é determinístico dessa forma."*

---

## 3. Guia Rápido de Respostas para Outras "Pegadinhas" da Banca

| Pergunta da Banca | O que responder |
|---|---|
| *"Por que vocês não descartaram os CPFs com dígito verificador inválido?"* | *"Porque o erro de digitação do CPF existia identicamente no Legado e no E-commerce. Descartá-lo eliminaria 9% dos pareamentos legítimos de clientes entre os dois sistemas. Um CPF inválido ainda é um identificador estável."* |
| *"Por que não usaram data de entrega nos atributos preditores da ABT?"* | *"Porque data de entrega é um evento posterior à compra e sofre de forte censura à direita próximo à data de corte. Usar status atual ou data de entrega vazaria se o pedido foi concluído com sucesso."* |
| *"Por que vocês criaram uma tabela de quarentena em vez de descartar os itens órfãos?"* | *"Para preservar a evidência contábil e a rastreabilidade. São R$ 2,79 milhões em itens que precisam ser auditados pela equipe de engenharia de software da origem, mas que não podiam entrar no DW para não quebrar a chave estrangeira nem inflar pedidos inexistentes."* |
| *"Por que o Orange e não apenas o Scikit-Learn?"* | *"Porque o Orange permite inspeção visual imediata das matrizes de confusão, curvas ROC interativas e distribuições dos dados através dos fluxos `.ows` fornecidos, garantindo que o experimento seja reproduzível tanto em ambiente gráfico quanto em script."* |
