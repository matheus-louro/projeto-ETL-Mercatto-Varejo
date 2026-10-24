#!/usr/bin/env python3
"""Carga atômica dos quatro fatos; decisões RDT-10 a RDT-13.
Grão pedido: um pedido por sistema/ID. Grão item: uma linha original de item.
Reutiliza dimensões cliente/produto/status da etapa 2.
"""
from decimal import Decimal
from sqlalchemy import text
from config import eng_dw, eng_mysql, eng_origem
from semana2_utils import escalar, verifica_sql, salva_json
from semana3_utils import executar, verifica_fks


def referencias():
    refs = {}
    for sistema, factory, sql in [
        ('LEGADO', eng_mysql, 'SELECT COUNT(*) n, SUM(VALOR_TOTAL) total FROM PEDIDOS'),
        ('ECOM', eng_origem, 'SELECT COUNT(*) n, SUM(total_amount + freight_amount) total FROM shop.orders')]:
        engine = factory()
        try:
            with engine.connect() as cx:
                refs[sistema] = dict(cx.execute(text(sql)).mappings().one())
        finally:
            engine.dispose()
    return refs


def dimensoes(cx, qa):
    verifica_sql(qa, cx, 'pedidos sem cliente correspondente', '''SELECT count(*)
        FROM cfm.pedidos_conformados p LEFT JOIN dw.dim_cliente c USING(cliente_sk)
        WHERE c.cliente_sk IS NULL''')
    if qa.falhou():
        raise RuntimeError('RDT-12: pedido sem cliente; corrigir o mapeamento antes da carga.')
    cx.execute(text('CREATE SCHEMA IF NOT EXISTS aud'))
    # A substituição dos fatos invalida a ABT, que depende da mesma versão da carga.
    cx.execute(text('TRUNCATE abt.recompra_90d, dw.fato_item_pedido, dw.fato_atendimento, '
                    'dw.fato_avaliacao, dw.fato_pedido, dw.dim_canal, dw.dim_tempo RESTART IDENTITY'))
    if escalar(cx, "SELECT to_regclass('abt.recompra_90d_vazamento') IS NOT NULL"):
        cx.execute(text('TRUNCATE abt.recompra_90d_vazamento'))
    for t in ('map_item', 'itens_quarentena', 'pedidos', 'atendimentos', 'avaliacoes', 'reconciliacao'):
        cx.execute(text(f'DROP TABLE IF EXISTS aud.{t}'))
    cx.execute(text('''INSERT INTO dw.dim_tempo
        WITH datas AS (
            SELECT data_pedido_local d FROM cfm.pedidos_conformados UNION ALL
            SELECT data_entrega_local FROM cfm.pedidos_conformados UNION ALL
            SELECT data_abertura FROM cfm.sac_conformado UNION ALL
            SELECT data_fechamento FROM cfm.sac_conformado UNION ALL
            SELECT data_avaliacao FROM cfm.avaliacoes_conformadas),
        serie AS (SELECT generate_series(LEAST(min(d),DATE '2022-12-01'),
            GREATEST(max(d),DATE '2026-03-31'), interval '1 day')::date d FROM datas)
        SELECT d,extract(year FROM d),extract(quarter FROM d),extract(month FROM d),
            extract(day FROM d),extract(isodow FROM d),
            (ARRAY['janeiro','fevereiro','março','abril','maio','junho','julho',
            'agosto','setembro','outubro','novembro','dezembro'])[extract(month FROM d)::int],
            extract(isodow FROM d)>=6 FROM serie'''))
    cx.execute(text('''INSERT INTO dw.dim_canal(canal_origem,canal_conformado,sistema)
        SELECT DISTINCT canal_origem,
            CASE canal_origem WHEN 'LOJA' THEN 'FISICO' WHEN 'TELEVENDAS' THEN 'TELEVENDAS'
              WHEN 'SITE' THEN 'ONLINE_PROPRIO' WHEN 'web' THEN 'ONLINE_PROPRIO'
              WHEN 'app' THEN 'ONLINE_PROPRIO' WHEN 'marketplace' THEN 'MARKETPLACE' END,
            sistema_origem FROM cfm.pedidos_conformados ORDER BY sistema_origem,canal_origem'''))
    verifica_sql(qa, cx, 'canal unico por sistema e rotulo', '''SELECT count(*) FROM
        (SELECT sistema,canal_origem FROM dw.dim_canal GROUP BY 1,2 HAVING count(*)<>1) x''')


def fatos(cx, qa):
    cx.execute(text('''INSERT INTO dw.fato_pedido(id_origem,sistema_origem,cliente_sk,
        data_pedido_sk,data_entrega_sk,canal_sk,status_sk,qtd_itens,valor_mercadoria,
        valor_frete,valor_desconto,valor_total,dias_entrega)
        SELECT p.id_origem,p.sistema_origem,p.cliente_sk,p.data_pedido_local,p.data_entrega_local,
            c.canal_sk,p.status_sk,p.qtd_itens,p.valor_mercadoria,p.valor_frete,p.valor_desconto,
            p.valor_total,p.dias_entrega FROM cfm.pedidos_conformados p
        JOIN dw.dim_canal c ON c.sistema=p.sistema_origem AND c.canal_origem=p.canal_origem
        ORDER BY p.sistema_origem,p.id_origem'''))
    cx.execute(text('''CREATE TABLE aud.pedidos AS SELECT d.pedido_sk,p.*
        FROM cfm.pedidos_conformados p JOIN dw.fato_pedido d USING(id_origem,sistema_origem)'''))
    cx.execute(text('ALTER TABLE aud.pedidos ADD PRIMARY KEY(pedido_sk)'))
    cx.execute(text('CREATE UNIQUE INDEX ON aud.pedidos(id_origem,sistema_origem)'))
    cx.execute(text('''CREATE TABLE aud.itens_quarentena AS SELECT i.*, 'PEDIDO_INEXISTENTE'::text motivo
        FROM cfm.itens_conformados i LEFT JOIN dw.fato_pedido p
        ON p.id_origem=i.id_pedido_origem AND p.sistema_origem=i.sistema_origem
        WHERE p.pedido_sk IS NULL'''))
    cx.execute(text('ALTER TABLE aud.itens_quarentena ADD PRIMARY KEY(id_item_origem)'))
    cx.execute(text('''CREATE TABLE aud.map_item AS SELECT
        row_number() OVER(ORDER BY i.sistema_origem,i.id_item_origem)::bigint item_sk,
        i.id_item_origem,i.sistema_origem,p.pedido_sk,pr.produto_sk,i.desconto_nao_informado
        FROM cfm.itens_conformados i JOIN dw.fato_pedido p
            ON p.id_origem=i.id_pedido_origem AND p.sistema_origem=i.sistema_origem
        LEFT JOIN dw.dim_produto pr ON pr.origem=i.sistema_origem AND
            COALESCE(pr.id_legado,pr.id_ecommerce)=i.id_produto_origem'''))
    cx.execute(text('ALTER TABLE aud.map_item ADD PRIMARY KEY(item_sk)'))
    cx.execute(text('CREATE UNIQUE INDEX ON aud.map_item(id_item_origem)'))
    cx.execute(text('''INSERT INTO dw.fato_item_pedido
        SELECT m.item_sk,m.pedido_sk,m.produto_sk,i.quantidade,i.valor_unitario,i.valor_desconto,i.valor_liquido
        FROM aud.map_item m JOIN cfm.itens_conformados i USING(id_item_origem) ORDER BY m.item_sk'''))
    cx.execute(text("SELECT setval(pg_get_serial_sequence('dw.fato_item_pedido','item_sk'), COALESCE(max(item_sk),1),count(*)>0) FROM dw.fato_item_pedido"))
    cx.execute(text('''INSERT INTO dw.fato_atendimento(protocolo,cliente_sk,pedido_sk,
        data_abertura_sk,data_fechamento_sk,canal,motivo_conformado,nota_satisfacao,horas_resolucao)
        SELECT s.protocolo,s.cliente_sk,p.pedido_sk,s.data_abertura,s.data_fechamento,
            s.canal,s.motivo_conformado,s.nota_satisfacao,s.horas_resolucao
        FROM cfm.sac_conformado s LEFT JOIN dw.fato_pedido p ON p.id_origem=s.id_pedido_origem
        ORDER BY s.protocolo'''))
    cx.execute(text('''CREATE TABLE aud.atendimentos AS SELECT f.atendimento_sk,f.pedido_sk,
        s.*, (f.pedido_sk IS NULL) pedido_nao_encontrado
        FROM cfm.sac_conformado s JOIN dw.fato_atendimento f USING(protocolo)'''))
    cx.execute(text('ALTER TABLE aud.atendimentos ADD PRIMARY KEY(atendimento_sk)'))
    cx.execute(text('''INSERT INTO dw.fato_avaliacao(review_id,pedido_sk,produto_sk,data_sk,
        nota,compra_verificada,votos_uteis)
        SELECT a.review_id,p.pedido_sk,a.produto_sk,a.data_avaliacao,a.nota,a.compra_verificada,a.votos_uteis
        FROM cfm.avaliacoes_conformadas a LEFT JOIN dw.fato_pedido p ON p.id_origem=a.order_ref
        ORDER BY a.review_id'''))
    cx.execute(text('''CREATE TABLE aud.avaliacoes AS SELECT f.avaliacao_sk,f.pedido_sk,
        a.review_id,a._linha_origem,a.order_ref,a.product_sku,a.cliente_sk,a.produto_sk,
        a.data_avaliacao,a.data_avaliacao_utc,a.raw_horario,a.fuso_assumido,
        a.produto_consta_no_pedido,a.rating_ausente,a.rating_nulo,a.tipo_rating_origem,
        (f.pedido_sk IS NULL) pedido_nao_encontrado,(f.produto_sk IS NULL) produto_nao_encontrado
        FROM cfm.avaliacoes_conformadas a JOIN dw.fato_avaliacao f USING(review_id)'''))
    cx.execute(text('ALTER TABLE aud.avaliacoes ADD PRIMARY KEY(avaliacao_sk)'))
    cx.execute(text('CREATE INDEX IF NOT EXISTS ix_fato_item_pedido_pedido ON dw.fato_item_pedido(pedido_sk)'))
    cx.execute(text('CREATE INDEX IF NOT EXISTS ix_fato_avaliacao_pedido ON dw.fato_avaliacao(pedido_sk)'))
    cx.execute(text('CREATE INDEX IF NOT EXISTS ix_fato_atendimento_cliente ON dw.fato_atendimento(cliente_sk)'))


def validar(cx, qa, refs):
    verifica_fks(cx, qa)
    for fato, cfm in [('fato_pedido','pedidos_conformados'), ('fato_atendimento','sac_conformado'),
                      ('fato_avaliacao','avaliacoes_conformadas')]:
        qa.igual('cardinalidade '+fato, escalar(cx,f'SELECT count(*) FROM dw.{fato}'),
                 escalar(cx,f'SELECT count(*) FROM cfm.{cfm}'))
    verifica_sql(qa,cx,'prazo_nao_negativo','SELECT count(*) FROM dw.fato_pedido WHERE dias_entrega<0')
    verifica_sql(qa,cx,'identidade financeira por pedido','''SELECT count(*) FROM dw.fato_pedido
        WHERE valor_total<>valor_mercadoria+valor_frete-valor_desconto''')
    verifica_sql(qa,cx,'reconciliacao itens por pedido','''SELECT count(*) FROM dw.fato_pedido p
        LEFT JOIN (SELECT pedido_sk,sum(quantidade) qtd,sum(quantidade*valor_unitario) bruto,
            sum(valor_desconto) desconto,sum(valor_linha) liquido FROM dw.fato_item_pedido GROUP BY 1) i USING(pedido_sk)
        WHERE (p.qtd_itens,p.valor_mercadoria,p.valor_desconto,p.valor_total-p.valor_frete)
            IS DISTINCT FROM (i.qtd,i.bruto,i.desconto,i.liquido)''')
    verifica_sql(qa,cx,'particao itens sem perda nem sobreposicao','''SELECT count(*) FROM
        cfm.itens_conformados i LEFT JOIN aud.map_item m USING(id_item_origem)
        LEFT JOIN aud.itens_quarentena q USING(id_item_origem)
        WHERE (m.item_sk IS NOT NULL)::int+(q.id_item_origem IS NOT NULL)::int<>1''')
    qa.igual('rastro de todas as linhas de item',escalar(cx,'SELECT count(*) FROM aud.map_item'),
             escalar(cx,'SELECT count(*) FROM dw.fato_item_pedido'))
    verifica_sql(qa,cx,'quarentena apenas pedidos inexistentes','''SELECT count(*)
        FROM aud.itens_quarentena q JOIN dw.fato_pedido p ON p.id_origem=q.id_pedido_origem''')
    verifica_sql(qa,cx,'vinculos e flags das avaliacoes','''SELECT count(*) FROM aud.avaliacoes a
        JOIN dw.fato_avaliacao f USING(avaliacao_sk) WHERE a.produto_consta_no_pedido IS DISTINCT FROM
        EXISTS(SELECT 1 FROM dw.fato_item_pedido i WHERE i.pedido_sk=f.pedido_sk AND i.produto_sk=f.produto_sk)
        OR a.pedido_nao_encontrado IS DISTINCT FROM (f.pedido_sk IS NULL)
        OR a.produto_nao_encontrado IS DISTINCT FROM (f.produto_sk IS NULL)''')
    verifica_sql(qa,cx,'SAC sem vinculos fabricados','''SELECT count(*) FROM aud.atendimentos a
        JOIN dw.fato_atendimento f USING(atendimento_sk) LEFT JOIN dw.fato_pedido p ON p.pedido_sk=f.pedido_sk
        WHERE a.pedido_nao_encontrado IS DISTINCT FROM (f.pedido_sk IS NULL)
        OR (f.pedido_sk IS NOT NULL AND (f.cliente_sk IS DISTINCT FROM p.cliente_sk
            OR a.id_pedido_origem IS DISTINCT FROM p.id_origem))''')
    cx.execute(text('''CREATE TABLE aud.reconciliacao(sistema TEXT PRIMARY KEY,
        pedidos_origem BIGINT, pedidos_dw BIGINT, total_origem NUMERIC(20,2),total_dw NUMERIC(20,2),
        desvio_relativo NUMERIC, tolerancia NUMERIC, consulta_origem TEXT)'''))
    for sistema, ref in refs.items():
        row = cx.execute(text('SELECT count(*) n,sum(valor_total) total FROM dw.fato_pedido WHERE sistema_origem=:s'),{'s':sistema}).mappings().one()
        original, destino = ref['total'] or Decimal(0), row['total'] or Decimal(0)
        delta = abs(destino-original) / abs(original) if original else (Decimal(0) if destino==0 else Decimal(1))
        qa.igual('pedidos diretos da origem '+sistema,row['n'],ref['n'])
        qa.entre('reconciliacao financeira '+sistema,delta,Decimal(0),Decimal('0.001'))
        qa.igual('itens carregados mais quarentena '+sistema,
            escalar(cx,f"SELECT (SELECT count(*) FROM aud.map_item WHERE sistema_origem='{sistema}')+(SELECT count(*) FROM aud.itens_quarentena WHERE sistema_origem='{sistema}')"),
            escalar(cx,f"SELECT count(*) FROM cfm.itens_conformados WHERE sistema_origem='{sistema}'"))
        consulta = 'SUM(PEDIDOS.VALOR_TOTAL)' if sistema=='LEGADO' else 'SUM(orders.total_amount + orders.freight_amount)'
        cx.execute(text('INSERT INTO aud.reconciliacao VALUES (:s,:no,:nd,:o,:d,:r,0.001,:q)'),
            dict(s=sistema,no=ref['n'],nd=row['n'],o=original,d=destino,r=delta,q=consulta))


def main():
    refs = referencias()
    def carga(cx,qa):
        dimensoes(cx,qa)
        fatos(cx,qa)
        validar(cx,qa,refs)
    engine=eng_dw()
    executar('03_carga_dw',engine,carga)
    with engine.connect() as cx:
        salva_json('semana3_reconciliacao.json',[dict(r) for r in cx.execute(text('SELECT * FROM aud.reconciliacao ORDER BY sistema')).mappings()])


if __name__=='__main__':
    main()
