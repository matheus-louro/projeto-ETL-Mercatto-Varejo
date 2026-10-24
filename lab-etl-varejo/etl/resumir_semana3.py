"""Resultados verificáveis para o RDT e o pacote de entrega."""
from sqlalchemy import text
from config import eng_dw
from semana2_utils import salva_json

CONSULTAS={
    'reconciliacao': 'SELECT * FROM aud.reconciliacao ORDER BY sistema',
    'itens': '''SELECT i.sistema_origem,count(*) total,
        count(*) FILTER(WHERE q.id_item_origem IS NOT NULL) quarentena,
        sum(q.valor_liquido) valor_quarentena
        FROM cfm.itens_conformados i LEFT JOIN aud.itens_quarentena q USING(id_item_origem)
        GROUP BY 1 ORDER BY 1''',
    'grao_item': '''SELECT count(*) grupos_produto_repetido,sum(n) linhas_nos_grupos,
        sum(n-1) linhas_colapsadas_se_agregar FROM
        (SELECT pedido_sk,produto_sk,count(*) n FROM dw.fato_item_pedido GROUP BY 1,2 HAVING count(*)>1) x''',
    'sac': '''SELECT count(*) total,count(*) FILTER(WHERE a.pedido_nao_encontrado) sem_pedido,
        count(*) FILTER(WHERE a.cpf_confere_com_cliente_pedido=false) cpf_divergente,
        count(*) FILTER(WHERE a.cpf_confere_com_cliente_pedido IS NULL) cpf_nao_comparavel,
        count(*) FILTER(WHERE a.data_abertura<p.data_pedido_sk) anterior_pedido
        FROM aud.atendimentos a LEFT JOIN dw.fato_pedido p USING(pedido_sk)''',
    'avaliacoes': '''SELECT count(*) total,count(*) FILTER(WHERE a.pedido_nao_encontrado) sem_pedido,
        count(*) FILTER(WHERE a.produto_nao_encontrado) sem_produto,
        count(*) FILTER(WHERE NOT a.produto_consta_no_pedido) produto_fora_pedido,
        count(*) FILTER(WHERE a.data_avaliacao<p.data_pedido_sk) anterior_pedido
        FROM aud.avaliacoes a LEFT JOIN dw.fato_pedido p USING(pedido_sk)''',
    'abt': '''SELECT count(*) clientes,sum(alvo_recompra_90d) positivos,
        avg(alvo_recompra_90d) taxa_alvo,sum(qtd_atendimentos_sac) atendimentos_elegiveis,
        sum(qtd_avaliacoes_consistentes) avaliacoes_elegiveis,
        count(*) FILTER(WHERE nota_media_avaliacoes IS NULL) clientes_sem_nota
        FROM abt.recompra_90d''',
    'qa_ultima_execucao': '''WITH ultima AS(SELECT etapa,max(executado_em) instante
        FROM qa.execucao_assercao GROUP BY etapa)
        SELECT q.etapa,count(*) assercoes,count(*) FILTER(WHERE NOT aprovado) falhas
        FROM qa.execucao_assercao q JOIN ultima u ON q.etapa=u.etapa AND q.executado_em=u.instante
        GROUP BY q.etapa ORDER BY q.etapa''',
    'contagens': '''SELECT 'dw.dim_cliente' tabela,count(*) linhas FROM dw.dim_cliente UNION ALL
        SELECT 'dw.dim_produto',count(*) FROM dw.dim_produto UNION ALL
        SELECT 'dw.dim_status',count(*) FROM dw.dim_status UNION ALL
        SELECT 'dw.dim_tempo',count(*) FROM dw.dim_tempo UNION ALL
        SELECT 'dw.dim_canal',count(*) FROM dw.dim_canal UNION ALL
        SELECT 'dw.fato_pedido',count(*) FROM dw.fato_pedido UNION ALL
        SELECT 'dw.fato_item_pedido',count(*) FROM dw.fato_item_pedido UNION ALL
        SELECT 'dw.fato_atendimento',count(*) FROM dw.fato_atendimento UNION ALL
        SELECT 'dw.fato_avaliacao',count(*) FROM dw.fato_avaliacao UNION ALL
        SELECT 'abt.recompra_90d',count(*) FROM abt.recompra_90d ORDER BY 1'''
}


if __name__=='__main__':
    with eng_dw().connect() as cx:
        resultados={nome:[dict(r) for r in cx.execute(text(sql)).mappings()]
                    for nome,sql in CONSULTAS.items()}
    salva_json('semana3_resultados.json',resultados)
    print(resultados)
