# Entrega 3 — execução, validação e restauração

## Conteúdo entregue

- Código das etapas 1 a 4 (versão correta da ABT) e scripts de validação.
- `Relatorio_Decisoes_RDT_Semana3.md`: fichas 10–13, reconciliação e desenho da ABT.
- RDT da semana 2 como contexto das decisões anteriores.
- `mercatto_semana3.sql`: dump SQL de `dw`, `abt`, `aud` e `qa`, com dados, sequências, índices e restrições.
- `validacao/`: resultados das asserções e referências de comparação integral.

A versão implementada inclui a carga do DW e a ABT correta. As etapas 3 e 4
são executadas nessa ordem.

## Executar em uma instalação nova

Na pasta `lab-etl-varejo`, com Docker em execução:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose logs seed
```

A configuração `ESCALA=1.0` reproduz as contagens do relatório. O seed gera
as fontes determinísticas e cria os bancos. O pipeline é executado após sua
conclusão bem-sucedida; cada etapa depende do código de saída zero da anterior:

```powershell
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
docker compose exec -T etl python 03_carga_dw.py
docker compose exec -T etl python 04_abt.py --correta
docker compose exec -T etl python resumir_semana3.py
```

Os resultados são gravados em `saida/`. A extração e conformação usam os scripts
de extração e conformação. A implementação das etapas 3 e 4 utiliza o DDL,
o gerador, os parâmetros analíticos e o framework fornecidos pelo laboratório.

## Repetir a carga e testar

Com as quatro etapas concluídas:

```powershell
docker compose exec -T etl python testar_semana3.py
docker compose exec -T etl python verificar_semana3.py --gravar-referencia
docker compose exec -T etl python 03_carga_dw.py
docker compose exec -T etl python 04_abt.py --correta
docker compose exec -T etl python verificar_semana3.py --comparar
```

`testar_semana3.py` modifica dados futuros apenas dentro de uma transação
revertida, compara todos os preditores e testa o bloqueio de pedido sem cliente.
`verificar_semana3.py` compara todas as linhas em ordem de PK, por SHA-256,
e também tipos, nulabilidade, restrições e sequências. Não inclui QA por padrão,
pois esse histórico cresce a cada execução.

A etapa 3 substitui atomicamente os fatos e invalida a ABT anterior; a etapa 4
reconstrói a ABT. Falha de asserção causa rollback e retorno diferente de zero.
A etapa 2 bloqueia a reconstrução de dimensões referenciadas por fatos ou ABT
preenchidos. A reexecução de **1 → 2 → 3 → 4** exige um destino vazio.

## Validar a cadeia em destino isolado

As origens e os arquivos permanecem os mesmos, somente o destino muda:

```powershell
docker compose exec -T pg_dw createdb -U postgres mercatto_teste_novo
docker cp sql/postgres-dw/01_schema_dw.sql lab_pg_dw:/tmp/schema_teste.sql
docker compose exec -T pg_dw psql -U postgres -d mercatto_teste_novo -v ON_ERROR_STOP=1 -f /tmp/schema_teste.sql
```

As quatro etapas utilizam as seguintes variáveis no `docker compose exec`:

```text
-e PG_DW_DSN=postgresql+psycopg2://postgres:postgres@pg_dw:5432/mercatto_teste_novo
-e DIR_SAIDA=/saida/teste_novo
```

Exemplo do primeiro comando:

```powershell
docker compose exec -T -e PG_DW_DSN=postgresql+psycopg2://postgres:postgres@pg_dw:5432/mercatto_teste_novo -e DIR_SAIDA=/saida/teste_novo etl python 01_extracao.py
```

A mesma configuração é aplicada a `02_transformacao.py`, `03_carga_dw.py` e
`04_abt.py --correta`. A comparação com a referência principal utiliza o mesmo
DSN e o `DIR_SAIDA` padrão, onde está armazenada a referência:

```powershell
docker compose exec -T -e PG_DW_DSN=postgresql+psycopg2://postgres:postgres@pg_dw:5432/mercatto_teste_novo etl python verificar_semana3.py --comparar --etapa 03_verificacao_cadeia
```

Esse teste reconstrói o destino desde o DDL vazio. Não representa uma nova
geração das origens: usa as fontes determinísticas já fornecidas pelo seed.

## Restaurar o dump entregue

Comandos executados em `Entrega3_Mercatto/lab-etl-varejo`. A restauração
depende somente do PostgreSQL de destino, sem necessidade de gerar as fontes:

```powershell
docker compose up -d pg_dw
docker compose exec -T pg_dw pg_isready -U postgres
docker compose exec -T pg_dw createdb -U postgres mercatto_entrega3
docker cp ../mercatto_semana3.sql lab_pg_dw:/tmp/mercatto_semana3.sql
docker compose exec -T pg_dw psql -U postgres -d mercatto_entrega3 -v ON_ERROR_STOP=1 -f /tmp/mercatto_semana3.sql
```

O banco de restauração deve estar vazio e ter nome disponível. O dump
contém o DDL e os dados completos dos quatro schemas.
Ele não contém `stg`/`cfm`, que são reconstruídos pelas etapas 1 e 2. Contém as
tabelas auxiliares usadas pela ABT e a quarentena dos itens, portanto permite
inspeção e reprodução da ABT diretamente sobre o estado restaurado.

Para comparar integralmente a restauração, incluindo QA, antes de executar
qualquer outra rotina no banco restaurado:

```powershell
docker compose up -d --build --no-deps etl
docker cp ../validacao/semana3_referencia_dump.json lab_etl:/tmp/semana3_referencia_dump.json
docker compose exec -T -e PG_DW_DSN=postgresql+psycopg2://postgres:postgres@pg_dw:5432/mercatto_entrega3 etl python verificar_semana3.py --comparar --incluir-qa --referencia /tmp/semana3_referencia_dump.json --etapa 03_verificacao_dump
```

Essa verificação acrescenta suas próprias asserções ao banco restaurado **após**
a comparação. Uma segunda comparação com QA passa a encontrar esse histórico
adicional. A repetição da comparação exata exige nova restauração em banco vazio.

## Conferir o resultado por SQL

```sql
SELECT * FROM aud.reconciliacao ORDER BY sistema;
SELECT sistema_origem, count(*), sum(valor_total)
FROM dw.fato_pedido GROUP BY sistema_origem;
SELECT count(*), sum(alvo_recompra_90d), avg(alvo_recompra_90d)
FROM abt.recompra_90d;

WITH ultima AS (
  SELECT etapa, max(executado_em) instante
  FROM qa.execucao_assercao GROUP BY etapa
)
SELECT q.etapa, count(*) assercoes,
       count(*) FILTER (WHERE NOT aprovado) falhas
FROM qa.execucao_assercao q
JOIN ultima u ON q.etapa=u.etapa AND q.executado_em=u.instante
GROUP BY q.etapa ORDER BY q.etapa;
```

Resultado de referência: 410.000 pedidos, 1.371.876 itens, 20.577 itens em
quarentena, 95.000 atendimentos, 160.000 avaliações, 110.195 clientes na ABT e
24.056 positivos. Diferença financeira zero nas duas origens. As últimas
execuções aprovadas da carga e da ABT têm, respectivamente, 35 e 12 asserções.
Os testes transacionais têm 6 asserções; reexecução/cadeia, 66 cada; restauração
incluindo QA, 70. O histórico mantém falhas de desenvolvimento, identificáveis
pela etapa e instante; elas não representam o estado da última carga aprovada.
