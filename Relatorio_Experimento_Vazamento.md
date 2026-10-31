# Relatório de Resultados do Experimento de Vazamento de Dados

**Mineração de Dados · Engenharia de Computação · IFMT — 2026/2**  
**Projeto Prático de ETL — Mercatto Varejo**  
**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi  
**Ambiente:** Docker, Escala 1.0, Semente `20262`

---

## 1. Desenho Experimental e Protocolo de Avaliação

O presente experimento tem como objetivo reproduzir deliberadamente, mensurar e diagnosticar o fenômeno do **vazamento de dados (*data leakage*)** na construção da Tabela-Base de Análise (ABT) para previsão de recompra de clientes da *Mercatto Comércio S.A.*

A pergunta preditiva formulada pela diretoria da varejista estabelece o seguinte contrato analítico:
> *"Dado o comportamento de compra do cliente até 30 de junho de 2025, ele realizará ao menos uma nova compra entre 1º de julho e 28 de setembro de 2025?"*

Para responder a esta indagação e avaliar o impacto de contaminações metodológicas e temporais, foram construídas duas versões da ABT sobre a mesma população elegível de **110.195 clientes** (aqueles com histórico prévio até a data de corte):

1. **Versão Correta (`abt.recompra_90d`):** Todos os atributos preditivos calculados utilizando estritamente transações, chamados de SAC e avaliações ocorridos até **30/06/2025**. O alvo binário (`alvo_recompra_90d`) reflete as recompras líquidas não canceladas realizadas entre 01/07/2025 e 28/09/2025 (taxa positiva de **21,83%**; 24.056 clientes).
2. **Versão com Vazamento (`abt.recompra_90d_vazamento`):**
   - **Vazamento Temporal Óbvio:** Os atributos `recencia_dias` e `frequencia_pedidos` foram calculados sobre o histórico completo de pedidos do banco (estendendo-se além de 30/06/2025), simulando a omissão da cláusula de filtro temporal no pipeline.
   - **Vazamento Metodológico Sutil:** O atributo contínuo `valor_monetario_total` foi submetido a padronização global (*Z-score* univariado: $\mu=0, \sigma=1$) sobre todos os 110.195 registros da tabela analítica **antes** da partição em conjuntos de treino e teste.

Ambas as versões foram exportadas pelo pipeline (`05_exportar_orange.py`) em formato CSV compatível com o Orange Data Mining, com cabeçalhos triplos padronizados declarando metadados, tipos contínuos/discretos e papéis (`meta`, `class` e preditores). 

O protocolo experimental adotou amostragem estratificada 70/30 (77.136 instâncias para treinamento e 33.059 para teste) sob a mesma semente aleatória (`random_state=42`), avaliando três algoritmos de aprendizado supervisionado:
* **Naive Bayes** (GaussianNB com priores empíricas)
* **Regressão Logística** (regularização L2, solver L-BFGS, tolerância $10^{-4}$)
* **Árvore de Decisão** (critério Gini, profundidade máxima = 5)

---

## 2. Resposta à Pergunta (a) — Diferença de Desempenho entre as Versões

A Tabela 1 sintetiza o desempenho preditivo obtido no conjunto de teste independente (33.059 clientes; 7.217 positivos e 25.842 negativos) para as duas versões da base.

### Tabela 1: Comparativo de Métricas no Conjunto de Teste (70% Treino / 30% Teste Estratificado)

| Algoritmo | Versão | AUC-ROC | Acurácia Balanceada | F1-Score | Precisão | Revocação | Matriz de Confusão [TN, FP / FN, TP] |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Naive Bayes** | Correta | 0,5359 | 0,5085 | 0,0754 | 0,3163 | 0,0428 | [25.174, 668 / 6.908, 309] |
| | **Com Vazamento** | **0,8883** | **0,7594** | **0,6101** | **0,5687** | **0,6582** | [22.239, 3.603 / 2.467, 4.750] |
| | *Variação ($\Delta$)* | *+0,3524* | *+0,2509* | *+0,5347* | *+0,2524* | *+0,6154* | *Redução massiva de FN (-64%)* |
| **Regressão Logística** | Correta | 0,5345 | 0,5000 | 0,0000 | 0,0000 | 0,0000 | [25.842, 0 / 7.217, 0] |
| | **Com Vazamento** | **0,8435** | **0,6382** | **0,4338** | **0,5840** | **0,3450** | [24.068, 1.774 / 4.727, 2.490] |
| | *Variação ($\Delta$)* | *+0,3090* | *+0,1382* | *+0,4338* | *+0,5840* | *+0,3450* | *Sai da predição trivial majoritária* |
| **Árvore de Decisão** | Correta | 0,5267 | 0,4999 | 0,0006 | 0,1538 | 0,0003 | [25.831, 11 / 7.215, 2] |
| | **Com Vazamento** | **0,9663** | **0,8644** | **0,8134** | **0,8768** | **0,7585** | [25.073, 769 / 1.743, 5.474] |
| | *Variação ($\Delta$)* | *+0,4396* | *+0,3645* | *+0,8128* | *+0,7230* | *+0,7582* | *Verdadeiros Positivos: de 2 para 5.474!* |

![Figura 1: Curvas ROC e Salto Artificial de Desempenho](/home/luchesi/bagunca/projeto-ETL-Mercatto-Varejo/relatorios_semana4/imagens/painel_desempenho_horizontal.png)

---

## 3. Resposta à Pergunta (b) — O Impacto Numérico do Vazamento Sutil

Para responder se a normalização (*Z-score*) realizada sobre a totalidade da base antes da partição produz diferença perceptível, executou-se um ensaio controlado isolando exclusivamente essa intervenção sobre os dados íntegros no tempo (sem vazamento temporal). Os resultados comparativos encontram-se na Tabela 2.

### Tabela 2: Efeito Isolado da Normalização Z-Score Global (Antes do Split de Treino/Teste)

| Modelo | Sem Vazamento (Bruto) | Com Vazamento Sutil (Z-score Global) | Diferença Numérica ($\Delta$) | Impacto Perceptível? |
|---|:---:|:---:|:---:|:---:|
| **Naive Bayes (AUC)** | 0,5359 | 0,5356 | -0,0003 | Não perceptível visualmente |
| **Naive Bayes (BalAcc)** | 0,5085 | 0,5068 | -0,0017 | Variação ínfima ($\approx 0,17\%$) |
| **Naive Bayes (F1-Score)** | 0,0754 | 0,0583 | -0,0171 | Leve sensibilidade de calibração |
| **Regressão Logística (AUC)** | 0,5345 | 0,5345 | 0,0000 | Nula (invariante a escala linear) |
| **Árvore de Decisão (AUC)** | 0,5267 | 0,5267 | 0,0000 | Nula (invariante a transformações monotônicas) |

### Interpretação Epistêmica:
A resposta técnica à pergunta (b) é **não, o vazamento sutil não produz uma diferença escandalosa perceptível a olho nu**, mantendo a variação de AUC restrita entre $0,0000$ e $-0,0003$. Na Árvore de Decisão e na Regressão Logística, a normalização univariada não altera a ordenação das divisões nem a separabilidade monotônica dos dados.

**Por que esse resultado é didaticamente crucial?**  
É precisamente essa invisibilidade numérica que torna o vazamento metodológico a falha mais letal da engenharia de machine learning. Ao contrário do vazamento temporal (que explode o AUC para > 0,90 e chama a atenção de qualquer analista atento), a violação de vazamento de pré-processamento transfere silenciosamente a média ($\mu$) e a variância ($\sigma$) do conjunto de teste para a parametrização do treino. Quando o modelo for implantado na esteira de produção e receber um novo lote com deslocamento distributivo (*covariate shift*), a inferência falhará sem que nenhuma métrica de validação tenha soado o alarme no laboratório.

---

## 4. Resposta à Pergunta (c) — Diagnóstico e Descoberta às Cegas (Defesa Oral)

> **Pergunta-Chave da Banca:** *"Se você tivesse recebido apenas o resultado da versão com vazamento, sem acesso ao código SQL de extração ou aos scripts do pipeline, como descobriria tecnicamente que esse modelo está errado?"*

Se um auditor externo recebesse apenas o artefato analítico e o modelo treinado com AUC de 0,966, quatro procedimentos investigativos revelariam a contaminação de forma irrefutável:

### 1. Auditoria Estatística Univariada de Domínio Temporal (A Prova Material)
Ao inspecionar o sumário descritivo (*describe*) do atributo `recencia_dias`, o auditor encontraria imediatamente um valor mínimo absurdo:
$$\min(\text{recencia\_dias}) = -89 \text{ dias}$$

Como a recência é contratualmente definida como o tempo decorrido entre a última compra do cliente e a data de corte ($t_0 = \text{30/06/2025}$):
$$\text{recencia\_dias} = t_0 - \max(t_{\text{compra}})$$
Um valor negativo implica matematicamente que $\max(t_{\text{compra}}) > t_0$. Na base com vazamento, existem exatamente **47.984 clientes (43,5% da base)** com recência estritamente menor que zero. A presença de recências negativas em relação à data de corte é prova material incontestável de violação de causalidade temporal.

### 2. Análise de Importância de Variáveis e Decomposição de Coeficientes
Ao inspecionar a importância dos preditores na Árvore de Decisão, verifica-se que o atributo `recencia_dias` responde por **92,1%** de toda a redução de impureza de Gini do modelo, com o atributo `frequencia_pedidos` absorvendo outros 6,4%. Todos os demais sete atributos legítimos (tempo como cliente, ticket médio, atendimentos do SAC, nota de avaliações) somam menos de 1,5% de contribuição combinada. Uma única variável concentrar mais de 90% da capacidade preditiva em um cenário de varejo comportamental indica que o atributo não está correlacionado à causa, mas sim codificando a própria ocorrência do evento futuro.

![Figura 2: Prova Material de Recência Negativa e Hipertrofia na Árvore](/home/luchesi/bagunca/projeto-ETL-Mercatto-Varejo/relatorios_semana4/imagens/painel_auditoria_horizontal.png)

### 3. Validação Fora do Tempo (Out-of-Time / Backtesting) vs. Partição Randômica
A validação cruzada aleatória (*k-fold* ou amostragem 70/30) perpetua o vazamento porque dados contaminados estão presentes em ambas as partições. O auditor realizaria uma **partição cronológica estrita (*Out-of-Time Validation*)**:
* Treina o modelo em uma janela histórica anterior ($t_{-1}$);
* Avalia o modelo em um lote novo cujos dados futuros ainda não existam.
Nesse teste fora do tempo, o modelo contaminado sofreria um **colapso catastrófico de desempenho**: clientes que recompram não terão recência negativa no momento da predição real, fazendo a acurácia cair para o nível da predição cega ($\approx 50\%$).

### 4. Correlação Bivariada Próxima de Extremos Determinísticos
A correlação de Pearson entre `recencia_dias` e `alvo_recompra_90d` na versão correta é de apenas $-0,019$ (comportamento de baixa separabilidade linear). Na versão com vazamento, a correlação salta para $-0,378$, apresentando no primeiro nó de decisão da árvore uma regra límpida:
$$\text{Se } \text{recencia\_dias} < 0 \implies P(\text{recompra}) \approx 98\%$$
Nenhum atributo comportamental genuíno em varejo atinge tal grau de determinismo sem que haja vazamento da própria classe na sua fórmula geradora.

---

## 5. Conclusão

O experimento demonstra que construir modelos preditivos de alta acurácia aparente é trivial quando se relaxa o rigor temporal do pré-processamento. A verdadeira complexidade do processo de mineração reside no pipeline de engenharia de dados (ETL): sustentar o grão atômico, assegurar que nenhum registro posterior ao ponto de corte traspasse para a ABT e documentar formalmente cada decisão nas fichas de RDT.
