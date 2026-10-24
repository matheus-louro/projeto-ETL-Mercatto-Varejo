#!/usr/bin/env python3
"""Construção transacional da ABT de recompra com corte temporal."""
import argparse
from sqlalchemy import text
from config import DATA_CORTE, DATA_FIM_ALVO, eng_dw
from semana2_utils import escalar, verifica_sql, salva_json
from semana3_utils import executar, verifica_fks

# Frequência/recência/valores referem-se a pedidos registrados, inclusive cancelados.
# Não usa status atual, entrega, cadastro atual ou votos nas variáveis preditoras.
COLUNAS = {
    'recencia_dias': 'INTEGER', 'frequencia_pedidos': 'INTEGER',
    'valor_monetario_total': 'NUMERIC(20,2)', 'ticket_medio': 'NUMERIC(20,4)',
    'tempo_como_cliente': 'INTEGER', 'qtd_atendimentos_sac': 'INTEGER',
    'qtd_avaliacoes_consistentes': 'INTEGER', 'nota_media_avaliacoes': 'NUMERIC(10,4)',
    'sem_nota_avaliacao': 'BOOLEAN',
}


def consulta():
    return f"""
    WITH historico AS (
        SELECT * FROM dw.fato_pedido WHERE data_pedido_sk<=DATE '{DATA_CORTE}'
    ), pedidos AS (
        SELECT cliente_sk,DATE '{DATA_CORTE}'-max(data_pedido_sk) recencia_dias,
            count(*)::int frequencia_pedidos,sum(valor_total)::numeric(20,2) valor_monetario_total,
            avg(valor_total)::numeric(20,4) ticket_medio,
            DATE '{DATA_CORTE}'-min(data_pedido_sk) tempo_como_cliente
        FROM historico GROUP BY cliente_sk
    ), sac AS (
        SELECT p.cliente_sk,count(*)::int n FROM dw.fato_atendimento s
        JOIN historico p USING(pedido_sk)
        WHERE s.data_abertura_sk<=DATE '{DATA_CORTE}' AND s.data_abertura_sk>=p.data_pedido_sk
        GROUP BY p.cliente_sk
    ), avaliacoes AS (
        SELECT p.cliente_sk,count(*)::int n,avg(a.nota)::numeric(10,4) media
        FROM dw.fato_avaliacao a JOIN historico p USING(pedido_sk)
        JOIN aud.avaliacoes v USING(avaliacao_sk)
        WHERE a.data_sk<=DATE '{DATA_CORTE}' AND a.data_sk>=p.data_pedido_sk
          AND v.produto_consta_no_pedido
        GROUP BY p.cliente_sk
    ), alvo AS (
        SELECT DISTINCT p.cliente_sk FROM dw.fato_pedido p JOIN dw.dim_status s USING(status_sk)
        WHERE p.data_pedido_sk>DATE '{DATA_CORTE}' AND p.data_pedido_sk<=DATE '{DATA_FIM_ALVO}'
          AND s.status_conformado<>'CANCELADO'
    )
    SELECT p.cliente_sk,DATE '{DATA_CORTE}' data_corte,
        (CASE WHEN alvo.cliente_sk IS NULL THEN 0 ELSE 1 END)::smallint alvo_recompra_90d,
        p.recencia_dias,p.frequencia_pedidos,p.valor_monetario_total,p.ticket_medio,p.tempo_como_cliente,
        coalesce(s.n,0)::int qtd_atendimentos_sac,coalesce(a.n,0)::int qtd_avaliacoes_consistentes,
        a.media nota_media_avaliacoes,(a.media IS NULL) sem_nota_avaliacao
    FROM pedidos p LEFT JOIN sac s USING(cliente_sk) LEFT JOIN avaliacoes a USING(cliente_sk)
    LEFT JOIN alvo USING(cliente_sk)
    """


def validar(cx, qa):
    qa.igual('populacao elegivel completa',escalar(cx,'SELECT count(*) FROM abt.recompra_90d'),
        escalar(cx,f"SELECT count(DISTINCT cliente_sk) FROM dw.fato_pedido WHERE data_pedido_sk<=DATE '{DATA_CORTE}'"))
    verifica_sql(qa,cx,'ABT grao cliente e corte', '''SELECT count(*) FROM
        (SELECT cliente_sk,data_corte FROM abt.recompra_90d GROUP BY 1,2 HAVING count(*)<>1) x''')
    verifica_sql(qa,cx,'ABT corte e alvo binario', f"SELECT count(*) FROM abt.recompra_90d WHERE data_corte<>DATE '{DATA_CORTE}' OR alvo_recompra_90d NOT IN(0,1)")
    qa.entre('taxa do alvo',escalar(cx,'SELECT avg(alvo_recompra_90d) FROM abt.recompra_90d'),0.02,0.60)
    # Recalcula os atributos de forma independente para toda a população.
    verifica_sql(qa,cx,'alvo confere com janela e status',f"""SELECT count(*) FROM abt.recompra_90d a
        WHERE (a.alvo_recompra_90d=1) IS DISTINCT FROM EXISTS(
            SELECT 1 FROM dw.fato_pedido p JOIN dw.dim_status s USING(status_sk)
            WHERE p.cliente_sk=a.cliente_sk AND p.data_pedido_sk BETWEEN DATE '{DATA_CORTE}'+1
            AND DATE '{DATA_FIM_ALVO}' AND s.status_conformado<>'CANCELADO')""")
    verifica_sql(qa,cx,'atributos pedidos recalculados ate corte',f"""SELECT count(*) FROM abt.recompra_90d a
        JOIN (SELECT cliente_sk,count(*)::int n,sum(valor_total)::numeric(20,2) total,
            round(avg(valor_total),4) ticket,min(data_pedido_sk) primeira,max(data_pedido_sk) ultima
            FROM dw.fato_pedido WHERE data_pedido_sk<DATE '{DATA_CORTE}'+1 GROUP BY 1) p USING(cliente_sk)
        WHERE (a.frequencia_pedidos,a.valor_monetario_total,a.ticket_medio,a.recencia_dias,a.tempo_como_cliente)
          IS DISTINCT FROM (p.n,p.total,p.ticket,DATE '{DATA_CORTE}'-p.ultima,DATE '{DATA_CORTE}'-p.primeira)""")
    verifica_sql(qa,cx,'atributos SAC recalculados ate corte',f"""SELECT count(*) FROM abt.recompra_90d a
        LEFT JOIN (SELECT p.cliente_sk,count(*) n FROM dw.fato_atendimento s
            JOIN dw.fato_pedido p USING(pedido_sk)
            WHERE p.data_pedido_sk<=DATE '{DATA_CORTE}' AND s.data_abertura_sk
                BETWEEN p.data_pedido_sk AND DATE '{DATA_CORTE}' GROUP BY 1) s USING(cliente_sk)
        WHERE a.qtd_atendimentos_sac IS DISTINCT FROM coalesce(s.n,0)""")
    verifica_sql(qa,cx,'avaliacoes validas recalculadas ate corte',f"""SELECT count(*) FROM abt.recompra_90d a
        LEFT JOIN (SELECT p.cliente_sk,count(*) n,round(avg(v.nota),4) media
            FROM dw.fato_avaliacao v JOIN dw.fato_pedido p USING(pedido_sk)
            WHERE p.data_pedido_sk<=DATE '{DATA_CORTE}' AND v.data_sk BETWEEN p.data_pedido_sk AND DATE '{DATA_CORTE}'
            AND EXISTS(SELECT 1 FROM dw.fato_item_pedido i WHERE i.pedido_sk=v.pedido_sk AND i.produto_sk=v.produto_sk)
            GROUP BY 1) v USING(cliente_sk)
        WHERE (a.qtd_avaliacoes_consistentes,a.nota_media_avaliacoes,a.sem_nota_avaliacao)
            IS DISTINCT FROM (coalesce(v.n,0),v.media,(v.media IS NULL))""")
    verifica_sql(qa,cx,'ABT contagens e recencias validas', '''SELECT count(*) FROM abt.recompra_90d
        WHERE frequencia_pedidos<1 OR recencia_dias<0 OR tempo_como_cliente<recencia_dias
          OR qtd_atendimentos_sac<0 OR qtd_avaliacoes_consistentes<0
          OR (nota_media_avaliacoes IS NOT NULL AND nota_media_avaliacoes NOT BETWEEN 1 AND 5)''')
    qa.igual('ABT PK e check preservados',escalar(cx,"""SELECT count(*) FROM pg_constraint
        WHERE conrelid='abt.recompra_90d'::regclass AND contype IN ('p','c')"""),2)
    verifica_fks(cx,qa,('abt',))


def construir(cx, qa):
    for col, tipo in COLUNAS.items():
        cx.execute(text(f'ALTER TABLE abt.recompra_90d ADD COLUMN IF NOT EXISTS {col} {tipo}'))
    cx.execute(text('TRUNCATE abt.recompra_90d'))
    cols = 'cliente_sk,data_corte,alvo_recompra_90d,'+','.join(COLUNAS)
    cx.execute(text(f'INSERT INTO abt.recompra_90d({cols}) '+consulta()))
    validar(cx,qa)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    grupo=ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--correta',action='store_true')
    grupo.add_argument('--vazamento',action='store_true')
    args=ap.parse_args()
    if args.vazamento:
        ap.error('Modo --vazamento não implementado. Modo disponível: --correta.')
    engine=eng_dw()
    executar('04_abt_correta',engine,construir)
    with engine.connect() as cx:
        resumo=dict(cx.execute(text('''SELECT count(*) clientes,sum(alvo_recompra_90d) positivos,
            avg(alvo_recompra_90d) taxa_alvo,sum(qtd_atendimentos_sac) atendimentos_elegiveis,
            sum(qtd_avaliacoes_consistentes) avaliacoes_elegiveis,
            count(*) FILTER(WHERE nota_media_avaliacoes IS NULL) clientes_sem_nota
            FROM abt.recompra_90d''')).mappings().one())
        salva_json('semana3_abt.json',resumo)
        print(resumo)


if __name__=='__main__':
    main()
