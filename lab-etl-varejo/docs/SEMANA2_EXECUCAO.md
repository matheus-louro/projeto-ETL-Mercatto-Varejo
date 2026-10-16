# Entrega 2 — execução e conferência

O RDT parcial está em `../Relatorio_Decisoes_RDT_Semana2.md`, relativo à pasta
do laboratório. A entrega inclui as etapas 1 e 2, seus módulos de apoio e as
asserções; não exige o carregamento dos fatos nem a ABT nesta semana.

## Executar

Na pasta `lab-etl-varejo`:

```powershell
docker compose up -d --build
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
```

Na primeira subida, aguarde o seed terminar. O Dockerfile instala também
`requirements_diagnostico.txt`, que complementa os requisitos originais com a
autenticação necessária ao MySQL 8. As origens são acessadas como `etl_ro`.

## Resultados

- `stg`: nove tabelas relacionais e dois arquivos, com conteúdo preservado.
- `cfm.clientes_origem`, `map_cliente_legado`, `map_cliente_ecom`: todos os IDs
  de origem e suas identidades unificadas, incluindo aliases duplicados.
- `cfm.itens_conformados`, `pedidos_conformados`: medidas financeiras, chaves
  de cliente e status, timestamps com fuso e datas de negócio.
- `cfm.map_produto_legado`, `map_produto_ecom`, `produtos_auditoria`: mapeamentos,
  indicadores de categoria ambígua e preços suspeitos.
- `cfm.sac_conformado`, `avaliacoes_conformadas`: eventos e vínculos, sem
  multiplicação de linhas; indicadores de ausência, invalidez e inconsistência.
- `cfm.inventario_ausencias`: classificação por tabela/campo, número absoluto,
  base de cálculo e tratamento de cada ausência observada.
- `dw.dim_cliente`, `dim_produto`, `dim_status`: dimensões preparadas.
- `qa.execucao_assercao`: resultados das verificações, incluindo histórico de falhas.

Valores monetários: `valor_mercadoria` é bruto, sem frete e antes de desconto;
`valor_total = valor_mercadoria + valor_frete - valor_desconto`. A data de corte
deve ser aplicada ao dia de negócio em `America/Sao_Paulo`, explicitado no RDT;
os instantes completos ficam armazenados com fuso. Configurações analíticas
originais não foram alteradas.

Os dados conformados ficam separados da staging bruta. Para integrar as etapas
futuras, consultar `cfm` e os respectivos mapas; os scripts 3 a 5 continuam com
o escopo original de desenvolvimento posterior. A etapa 2 rejeita fatos/ABT já
preenchidos antes de reconstruir dimensões, evitando apagar trabalho posterior.

## Verificar reexecução

Depois de uma execução bem-sucedida:

```powershell
docker compose exec -T etl python verificar_semana2.py --gravar-referencia
docker compose exec -T etl python 01_extracao.py
docker compose exec -T etl python 02_transformacao.py
docker compose exec -T etl python verificar_semana2.py --comparar
```

São comparados contagem e SHA-256 de todas as linhas das 25 tabelas de saída,
ordenadas por chave. Apenas o timestamp de auditoria `_extraido_em` é excluído.
Falha de asserção ou exceção faz o comando retornar código diferente de zero.

Arquivos de conferência na pasta `saida`:

- `semana2_contagens_extracao.json`;
- `semana2_resultados.json`;
- `semana2_qa_extracao.json`, `semana2_qa_transformacao.json`;
- `semana2_referencia.json`, `semana2_verificacao.json`, `semana2_qa_reexecucao.json`.

Para consultar a última execução de cada etapa, sem apagar falhas históricas:

```sql
SELECT q.etapa, COUNT(*) AS assercoes,
       COUNT(*) FILTER (WHERE NOT q.aprovado) AS falhas
FROM qa.execucao_assercao q
WHERE q.executado_em = (
    SELECT MAX(x.executado_em) FROM qa.execucao_assercao x
    WHERE x.etapa = q.etapa)
GROUP BY q.etapa ORDER BY q.etapa;
```
