#!/usr/bin/env python3
"""
Gera o Relatório de Decisões de Transformação (RDT) Final unificado (Fichas 01 a 17),
Tabela-Resumo e Reflexão Final, compilando para PDF via WeasyPrint.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path("/home/luchesi/bagunca/projeto-ETL-Mercatto-Varejo")
RDT2_PATH = ROOT / "Relatorio_Decisoes_RDT_Semana2.md"
RDT3_PATH = ROOT / "Relatorio_Decisoes_RDT_Semana3.md"
RDT_FINAL_MD = ROOT / "Relatorio_Decisoes_RDT_Final.md"
RDT_FINAL_PDF = ROOT / "Relatorio_Decisoes_RDT_Final.pdf"

rdt2 = RDT2_PATH.read_text(encoding="utf-8")
rdt3 = RDT3_PATH.read_text(encoding="utf-8")

# Extrair fichas da Semana 2: RDT-01 a RDT-09, RDT-16, RDT-17
def extrair_ficha_md(texto, inicio_re, fim_re):
    m_ini = re.search(inicio_re, texto, re.MULTILINE)
    if not m_ini:
        return ""
    start = m_ini.start()
    if fim_re:
        m_fim = re.search(fim_re, texto[start:], re.MULTILINE)
        if m_fim:
            end = start + m_fim.start()
            return texto[start:end].strip()
    return texto[start:].strip()

f01 = extrair_ficha_md(rdt2, r"^## RDT-01", r"^## RDT-02")
f02 = extrair_ficha_md(rdt2, r"^## RDT-02", r"^## RDT-03")
f03 = extrair_ficha_md(rdt2, r"^## RDT-03", r"^## RDT-04")
f04 = extrair_ficha_md(rdt2, r"^## RDT-04", r"^## RDT-05")
f05 = extrair_ficha_md(rdt2, r"^## RDT-05", r"^## RDT-06")
f06 = extrair_ficha_md(rdt2, r"^## RDT-06", r"^## RDT-07")
f07 = extrair_ficha_md(rdt2, r"^## RDT-07", r"^## RDT-08")
f08 = extrair_ficha_md(rdt2, r"^## RDT-08", r"^## RDT-09")
f09 = extrair_ficha_md(rdt2, r"^## RDT-09", r"^## RDT-13")
f16 = extrair_ficha_md(rdt2, r"^## RDT-16", r"^## RDT-17")
f17 = extrair_ficha_md(rdt2, r"^## RDT-17", r"$")

# Extrair fichas da Semana 3: RDT-10, RDT-11, RDT-12, RDT-13
f10 = extrair_ficha_md(rdt3, r"^## 2\. Ficha RDT-10", r"^## 3\. Ficha RDT-11")
f11 = extrair_ficha_md(rdt3, r"^## 3\. Ficha RDT-11", r"^## 4\. Ficha RDT-12")
f12 = extrair_ficha_md(rdt3, r"^## 4\. Ficha RDT-12", r"^## 5\. Ficha RDT-13")
f13 = extrair_ficha_md(rdt3, r"^## 5\. Ficha RDT-13", r"^## 6\. Reconciliação")

# Ajustar títulos para padronização ## RDT-XX
f10 = f10.replace("## 2. Ficha RDT-10 —", "## RDT-10 —")
f11 = f11.replace("## 3. Ficha RDT-11 —", "## RDT-11 —")
f12 = f12.replace("## 4. Ficha RDT-12 —", "## RDT-12 —")
f13 = f13.replace("## 5. Ficha RDT-13 —", "## RDT-13 —")

# Novas Fichas da Semana 4
f14 = """## RDT-14 — Desenho dos atributos da ABT e garantia de corte temporal (sem vazamento)

**Etapa:** `04_abt.py --correta`.

**O que o dado mostrava:** 110.195 clientes elegíveis (com ao menos um pedido registrado até 30/06/2025). As transações cobrem de 2023 até novembro de 2025. Calcular métricas agregadas sem congelamento estrito de tempo em 30/06/2025 permitiria que transações ocorridas durante a janela do alvo (01/07 a 28/09/2025) contaminassem os atributos preditores de comportamento prévio.

**Alternativas consideradas:**
1. Utilizar toda a base disponível e definir atributos em relação à data corrente da execução: simples e comum em análises ad-hoc, mas causa vazamento temporal catastrófico (o modelo decora o futuro).
2. Congelar estritamente os fatos em `data_pedido_sk <= '2025-06-30'` e definir o alvo na janela `2025-07-01` a `2025-09-28`: garante que os 9 preditores comportamentais reflitam exclusivamente o estado de conhecimento disponível na data de corte.

**Decisão e justificativa:** Alternativa 2. A ABT correta congela as variáveis preditoras em $t_0 = \\text{30/06/2025}$. `recencia_dias` mede $t_0 - \\max(t_{\\text{compra}})$; `frequencia_pedidos`, `valor_monetario_total` e `ticket_medio` agregam exclusivamente pedidos registrados até $t_0$. Atendimentos e avaliações só entram se a abertura ocorreu entre o pedido e a data de corte. O status dos pedidos não foi filtrado para os preditores porque a origem não preserva o log temporal de mudanças de estado (evitando vazamento de status).

**O que se perde:** Perde-se a informação transacional recente para efeitos de descrição histórica do cliente; descarta-se avaliações e chamados posteriores a $t_0$. Os dados permanecem preservados no DW; a restrição é estritamente de corte analítico.

**Registros afetados:** 110.195 clientes populam a ABT; 24.056 clientes (21,83%) sinalizados como positivos no alvo. 68.406 pedidos posteriores a 30/06/2025 foram excluídos do cálculo das variáveis preditivas.

**Asserções associadas:** `populacao elegivel completa`, `ABT grao cliente e corte`, `ABT corte e alvo binario`, `taxa do alvo`, `atributos pedidos recalculados ate corte`, `ABT contagens e recencias validas` (recência $\\ge 0$). Teste transacional de mutação do futuro com hash invariante."""

f15 = """## RDT-15 — Vazamentos introduzidos deliberadamente na versão de comparação

**Etapa:** `04_abt.py --vazamento`.

**O que o dado mostrava:** Na versão correta, a capacidade preditiva legítima das variáveis RFM é modesta (AUC $\\approx 0,53$), pois o comportamento de recompra é ruidoso e a janela alvo tem 21,8% de positivos. Para conduzir o experimento pedagógico exigido pela disciplina, era necessário produzir e mensurar o efeito de vazamento temporal grosseiro e vazamento metodológico sutil.

**Alternativas consideradas:**
1. Introduzir a própria variável alvo como preditora com ruído aleatório: artificial, não reproduz os erros metodológicos da engenharia de dados.
2. Omitir a cláusula de corte temporal nos atributos de pedidos (`recencia_dias` e `frequencia_pedidos`) e normalizar globalmente `valor_monetario_total` via Z-score antes da partição treino/teste: reproduz os dois erros mais frequentes em pipelines de mineração em produção.

**Decisão e justificativa:** Alternativa 2. Criou-se a tabela `abt.recompra_90d_vazamento` mantendo os mesmos 110.195 clientes e o mesmo alvo. Para `recencia_dias` e `frequencia_pedidos`, utilizou-se `dw.fato_pedido` sem restrição temporal, permitindo que compras da janela do alvo influenciem o cálculo. Para `valor_monetario_total`, calculou-se o Z-score univariado ($\mu=0, \sigma=1$) sobre todos os clientes antes do particionamento.

**O que se perde:** Perde-se a validade científica do modelo preditivo para uso em produção (o modelo torna-se inútil na prática, funcionando apenas em laboratório). Preserva-se o valor didático do contraexemplo mensurado.

**Registros afetados:** 110.195 registros afetados na ABT; 47.984 clientes (43,5% da base) tiveram recência calculada como negativa ($< 0$ dias) e frequência inflada por compras futuras. 100% dos clientes tiveram `valor_monetario_total` normalizado com parâmetros globais.

**Asserções associadas:** `populacao elegivel completa vazamento`, `taxa do alvo vazamento`, `vazamento temporal recencias negativas detectadas` ($\ge 1$), `vazamento temporal frequencias infladas` ($\ge 1$), `vazamento sutil media zscore global` (entre $-0,01$ e $+0,01$), `vazamento sutil desvio zscore global` (entre $0,99$ e $1,01$)."""

tabela_resumo = """---

## Tabela-Resumo de Todas as Decisões de Transformação

| Ficha | Decisão Central | Registros Afetados | % da Base | Informação Perdida / Limitação Assumida |
|---|---|---:|---:|---|
| **RDT-01** | Carga completa em lotes de 10.000 para camada `stg` | 2.205.864 | 100,00% | Não mantém histórico de snapshots anteriores em staging |
| **RDT-02** | Unificação de clientes por CPF preservando DV inválido | 118.215 | 89,42% | ~15% de clientes sobrepostos sem CPF comum não são unidos |
| **RDT-03** | Resolução determinística de duplicatas internas do legado | 1.984 | 4,20% | Prioriza cadastro mais antigo; campos conflitantes descartados |
| **RDT-04** | Conformação de status (`payment_declined` $\\to$ `CANCELADO`) | 13.990 | 3,41% | Perde distinção entre cancelamento voluntário e recusa bancária |
| **RDT-05** | Harmonização monetária (adiciona frete ao e-commerce) | 280.000 | 68,29% | Altera conceito de `total_amount` original para faturamento com frete |
| **RDT-06** | Sentinela `-1` em desconto vira zero; preserva frete negativo | 4.056 | 0,29% | Desconto real omitido na origem é irrecuperável |
| **RDT-07** | Mapeamento da taxonomia de categorias em árvore | 3.000 | 100,00% | Rótulos genéricos (`DIVERSOS`, `OUTROS`) classificados como indefinidos |
| **RDT-08** | Tratamento de ausências com sentinela `1900-01-01` $\\to$ `NULL` + flag | 1.025 | 0,79% | Data real de entrega de pedidos sentinela é irrecuperável |
| **RDT-09** | Padronização temporal em UTC e dia de negócio local | 130.000 | 31,71% | Suposição de fuso `America/Sao_Paulo` para datas sem offset |
| **RDT-10** | Quarentena isolada de 20.577 itens órfãos sem pedido | 20.577 | 1,48% | Itens fora do fato de vendas; faturamento de R$ 2,79 mi não atribuível |
| **RDT-11** | Grão atômico estrito e prevenção de multiplicação em fatos | 2.036.876 | 100,00% | Campos originais brutos exigem consulta a tabelas de auditoria |
| **RDT-12** | Integridade estrita pedido $\\to$ cliente com bloqueio de carga | 0 | 0,00% | Sacrifica disponibilidade da carga se surgir cliente não mapeado |
| **RDT-13** | Associação de arquivos restrita a vínculos cronológicos válidos | 255.000 | 100,00% | Autoria de SAC e avaliações não comprovadas; forte redução na ABT |
| **RDT-14** | Desenho da ABT correta com congelamento em 30/06/2025 | 110.195 | 100,00% | Desconsidera histórico posterior a $t_0$ nas variáveis preditivas |
| **RDT-15** | Vazamento temporal e metodológico introduzido na ABT teste | 110.195 | 100,00% | Modelo torna-se cientificamente inválido para predição real |
| **RDT-16** | Deduplicação exata de protocolos repetidos do SAC | 1.140 | 1,19% | Descarta protocolos duplicados de mesma data e texto idênticos |
| **RDT-17** | Preservação de preços suspeitos com flag de magnitude | 18 | 0,15% | Preços 10× anômalos mantidos para fidelidade contábil |
"""

reflexao_final = """---

## Reflexão Final

### 1. Qual das decisões acima mudaria mais o resultado do modelo se tivesse sido tomada de outro modo? Vocês testaram, ou é uma hipótese?

A decisão que mais afeta o modelo é a **RDT-14 (Corte Temporal Estrito)** em contraste com a **RDT-15 (Vazamento Temporal)**. Isso não é uma hipótese: foi comprovado experimentalmente. Ao omitirmos a fronteira em 30/06/2025, a AUC-ROC da Árvore de Decisão salta de 0,5267 para 0,9663 e a do Naive Bayes de 0,5359 para 0,8883, criando uma ilusão de precisão provocada por recências negativas geradas após o corte.

No plano do negócio legítimo, a que mais alteraria o resultado é a **RDT-04 (Conformação de Status no Alvo)**. Ao convergir `payment_declined` para `CANCELADO` e excluí-los da recompra positiva, a taxa do alvo fixou-se em 21,83%. Se tratássemos recusas de pagamento como intenção válida de compra, os positivos subiriam para ~26,8%, alterando sensivelmente a calibração de probabilidades e a matriz de confusão. Testamos essa sensibilidade na Semana 3 e confirmamos que a regra do alvo é a alavanca mais influente sobre o classificador.

### 2. Alguma decisão que vocês tomaram por conveniência técnica teria consequência sobre pessoas reais, se este fosse um sistema em produção? Qual?

Sim. A decisão na **RDT-02** de unificar clientes prioritariamente pelo CPF — mesmo preservando dígitos inválidos — deixa de fora cerca de 15% dos clientes sobrepostos entre o Legado e o E-commerce que tinham CPF ausente em uma das pontas.

Em produção, para dimensionar retenção e conceder benefícios a clientes com risco de churn, essa escolha técnica fragmenta o indivíduo em duas contas distintas no Data Warehouse. Um cliente fiel que compra nas lojas físicas e no site tem seu histórico dividido pela metade: frequência e valor monetário são subestimados, classificando-o erroneamente como cliente de baixo valor ou em abandono (*falso churn*). Ele deixaria de receber ofertas exclusivas e programas VIP aos quais teria direito pelo volume consolidado. Escolhas técnicas de ETL nunca são neutras: elas distribuem diretamente incentivos e tratamentos a pessoas reais."""

documento_completo = f"""# Registro de Decisões de Transformação (RDT) — Documento Integral

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

{f01}

---

{f02}

---

{f03}

---

{f04}

---

{f05}

---

{f06}

---

{f07}

---

{f08}

---

{f09}

---

{f10}

---

{f11}

---

{f12}

---

{f13}

---

{f14}

---

{f15}

---

{f16}

---

{f17}

{tabela_resumo}

{reflexao_final}
"""

RDT_FINAL_MD.write_text(documento_completo, encoding="utf-8")
print(f"RDT Final MD gerado com sucesso: {RDT_FINAL_MD} ({len(documento_completo)} caracteres)")

# Compilar para HTML e PDF via WeasyPrint
html_temp = ROOT / "relatorios_semana4" / "rdt_final.html"
css_rdt = ROOT / "relatorios_semana4" / "estilo_relatorio.css"

subprocess.run(["pandoc", str(RDT_FINAL_MD), "-o", str(html_temp), "--standalone"], check=True)
subprocess.run(["/home/luchesi/.local/bin/weasyprint", "-s", str(css_rdt), str(html_temp), str(RDT_FINAL_PDF)], check=True)
print(f"RDT Final PDF compilado com sucesso: {RDT_FINAL_PDF}")
