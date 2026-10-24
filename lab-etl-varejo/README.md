# ETL Mercatto Varejo

Projeto prático de Mineração de Dados — Engenharia da Computação, IFMT, 2026/2.

**Equipe:** Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi.

Integração de quatro fontes heterogêneas em um esquema estrela e construção de
uma base analítica para previsão de recompra. A escala 1,0 contém 2.205.864
registros nas fontes, incluindo as categorias do e-commerce.

## Implementação

| Etapa | Script | Resultado |
|---|---|---|
| Perfilamento | `00_perfilamento.py` | Descrição das fontes |
| Extração | `01_extracao.py` | Cópias integrais e tipadas em `stg` |
| Conformação | `02_transformacao.py` | Identidades, medidas, mapas e indicadores em `cfm` |
| Carga | `03_carga_dw.py` | Dimensões, quatro fatos, quarentena e auditoria |
| ABT correta | `04_abt.py --correta` | Uma linha por cliente na data de corte |
| Exportação | `05_exportar_orange.py` | CSV das ABTs disponíveis no formato do Orange |

O modo experimental `04_abt.py --vazamento` não está implementado nesta versão.

## Documentação

- [RDT da Semana 2](../Relatorio_Decisoes_RDT_Semana2.md): decisões de extração e conformação.
- [RDT da Semana 3](../Relatorio_Decisoes_RDT_Semana3.md): fichas 10–13, reconciliação e desenho da ABT.
- [Execução e conferência das etapas 1 e 2](docs/SEMANA2_EXECUCAO.md).
- [Execução, testes e restauração do DW](docs/SEMANA3_EXECUCAO.md).
- [Execução do diagnóstico](docs/DIAGNOSTICO_EXECUCAO.md).
- [Dicionário de dados](docs/DICIONARIO_DE_DADOS.md).
- [Resultados de validação da Semana 3](../validacao/semana3/): asserções, contagens e referências de comparação.

## Ambiente

Requisitos: Docker e Docker Compose v2. O ambiente fornecido recomenda 8 GB de
RAM. A configuração `ESCALA=1.0` reproduz as contagens dos relatórios; escalas
menores geram populações diferentes. A construção inicial das imagens depende
de acesso à internet. O Orange é executado fora dos contêineres.

| Serviço | Função | Acesso local |
|---|---|---|
| `mysql_legado` | ERP legado, MySQL 8, `latin1`, somente leitura | `localhost:3307`, `etl_ro` / `etl_ro` |
| `pg_ecommerce` | E-commerce, PostgreSQL 16, UTF-8, somente leitura | `localhost:5433`, `etl_ro` / `etl_ro` |
| `pg_dw` | Destino analítico, PostgreSQL 16 | `localhost:5434`, `postgres` / `postgres` |
| `adminer` | Consulta aos bancos por interface web | <http://localhost:8080> |
| `etl` | Execução do pipeline em Python | `docker compose exec etl bash` |

As fontes de arquivo são `dados/atendimentos_sac.csv` e
`dados/avaliacoes_marketplace.json`. O serviço `seed` gera os dados com semente
fixa e inicializa os bancos. O acesso ETL às duas origens relacionais utiliza
usuários de somente leitura.

## Execução em instalação nova

Comandos na pasta `lab-etl-varejo`:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose logs seed
```

A execução do pipeline depende da conclusão bem-sucedida do `seed`.
Cada etapa deve encerrar com código zero antes da execução da etapa seguinte.

```powershell
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
docker compose exec -T etl python 03_carga_dw.py
docker compose exec -T etl python 04_abt.py --correta
```

O perfilamento e a exportação são executados pelos comandos:

```powershell
docker compose exec -T etl python 00_perfilamento.py
docker compose exec -T etl python 05_exportar_orange.py
```

## Camadas e rastreabilidade

- `stg`: cópia fiel das fontes, com metadados de procedência.
- `cfm`: dados conformados e mapas de identidade das etapas 1 e 2.
- `dw`: dimensões e fatos do esquema estrela.
- `abt`: base de recompra com corte em 30/06/2025 e alvo entre 01/07 e 28/09/2025.
- `aud`: quarentena, rastreabilidade de itens e arquivos e reconciliação financeira.
- `qa`: histórico das asserções de qualidade por etapa.

A etapa 2 exige destino sem fatos ou ABT preenchidos. A etapa 3 substitui os
fatos atomicamente e invalida a ABT anterior. A etapa 4 reconstrói a ABT a partir
do DW carregado. Os testes de cadeia completa utilizam um banco de destino vazio.

Os módulos `semana2_utils.py` e `semana3_utils.py` concentram funções de apoio.
`verificar_semana2.py` e `verificar_semana3.py` comparam reexecuções;
`testar_semana3.py` verifica invariância temporal e bloqueio por cliente ausente.
Os resultados em JSON são gravados em `saida/`.

## Consulta às asserções

```sql
WITH ultima AS (
  SELECT etapa, max(executado_em) instante
  FROM qa.execucao_assercao GROUP BY etapa
)
SELECT q.etapa, count(*) assercoes,
       count(*) FILTER (WHERE NOT q.aprovado) falhas
FROM qa.execucao_assercao q
JOIN ultima u ON q.etapa=u.etapa AND q.executado_em=u.instante
GROUP BY q.etapa ORDER BY q.etapa;
```

O histórico conserva execuções de desenvolvimento. A avaliação do estado
validado considera a última execução de cada etapa. As instruções de
restauração do dump e comparação integral estão em
[SEMANA3_EXECUCAO.md](docs/SEMANA3_EXECUCAO.md).

## Diagnóstico de execução

| Ocorrência | Verificação técnica |
|---|---|
| `LOAD DATA LOCAL INFILE` recusado | O MySQL utiliza `--local-infile=1`, conforme o Compose fornecido. |
| Acentuação incorreta no legado | A conexão deve respeitar `charset=latin1`, definido em `config.py`. |
| Falha no `seed` | O diagnóstico está disponível em `docker compose logs seed`. |
| Falha de autenticação PyMySQL/MySQL 8 | A imagem ETL instala `cryptography` por `requirements_diagnostico.txt`. |
| Arquivo incompatível com Orange | Os CSVs de `saida/` gerados pelo exportador incluem cabeçalho de três linhas com tipos e papéis. |
