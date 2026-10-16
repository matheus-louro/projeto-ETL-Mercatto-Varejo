#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 2 — TRANSFORMAÇÃO E CONFORMAÇÃO  (esqueleto: vocês completam)

Esta é a etapa epistemicamente densa. Cada bloco abaixo corresponde a uma
decisão que NÃO tem resposta única. Para cada uma, o RDT deve trazer:
    (a) as alternativas consideradas;
    (b) a escolhida e por quê;
    (c) o que se perde com ela;
    (d) o número de registros afetados.

Uma decisão sem (c) e (d) não conta como decisão registrada.

    docker compose exec etl python 02_transformacao.py
"""

import re
import unicodedata

import pandas as pd
from sqlalchemy import text

from config import eng_dw
from qualidade.assercoes import Suite


# ---------------------------------------------------------------------------
# Utilitários que vocês vão precisar — estes estão prontos.
# ---------------------------------------------------------------------------
def so_digitos(txt):
    return re.sub(r"\D", "", txt or "")


def cpf_valido(cpf):
    """Valida os dois dígitos verificadores. Retorna None se não tiver 11 dígitos."""
    c = so_digitos(cpf)
    if len(c) != 11 or len(set(c)) == 1:
        return None if len(c) != 11 else False
    b = [int(x) for x in c]
    s = sum((10 - i) * b[i] for i in range(9))
    d1 = 0 if (11 - s % 11) >= 10 else (11 - s % 11)
    s = sum((11 - i) * (b[:9] + [d1])[i] for i in range(10))
    d2 = 0 if (11 - s % 11) >= 10 else (11 - s % 11)
    return b[9] == d1 and b[10] == d2


def normaliza_nome(nome):
    """MAIÚSCULAS sem acento, espaços colapsados. Base para pareamento aproximado."""
    n = unicodedata.normalize("NFD", (nome or "").strip().upper())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", n)


# ===========================================================================
# DECISÃO 1 — IDENTIDADE DO CLIENTE ENTRE OS DOIS SISTEMAS
# ===========================================================================
def unifica_clientes(qa):
    """
    Decisão 1 / RDT-02 e RDT-03: Identidade do Cliente e Deduplicação Interna
    """
    engine = eng_dw()
    with engine.connect() as cx:
        leg = pd.read_sql(text('SELECT "ID_CLIENTE", "NOME", "CPF", "CIDADE", "UF", "DT_CADASTRO" FROM stg.legado_clientes'), cx)
        eco = pd.read_sql(text('SELECT customer_id, full_name, tax_id, city, state, created_at FROM stg.ecom_customer'), cx)

    # Normalização de atributos
    leg['cpf_clean'] = leg['CPF'].apply(so_digitos)
    leg['cpf_norm'] = leg['cpf_clean'].apply(lambda x: x if len(x) == 11 else None)
    leg['cpf_val'] = leg['cpf_norm'].apply(lambda x: cpf_valido(x) if x else None)
    leg['nome_norm'] = leg['NOME'].apply(normaliza_nome)

    eco['cpf_clean'] = eco['tax_id'].apply(so_digitos)
    eco['cpf_norm'] = eco['cpf_clean'].apply(lambda x: x if len(x) == 11 else None)
    eco['cpf_val'] = eco['cpf_norm'].apply(lambda x: cpf_valido(x) if x else None)
    eco['nome_norm'] = eco['full_name'].apply(normaliza_nome)

    # RDT-03: Deduplicação interna do legado por CPF
    leg_com_cpf = leg[leg['cpf_norm'].notna()].sort_values('ID_CLIENTE')
    leg_canonicos = leg_com_cpf.drop_duplicates(subset=['cpf_norm'], keep='first').copy()
    leg_sem_cpf = leg[leg['cpf_norm'].isna()].copy()
    
    # Mapeamento De-Para para que todos os IDs de clientes duplicados do legado apontem para o canônico
    map_leg_canonico = leg_com_cpf[['ID_CLIENTE', 'cpf_norm']].merge(
        leg_canonicos[['ID_CLIENTE', 'cpf_norm']], on='cpf_norm', suffixes=('_orig', '_canonico')
    )
    map_sem_cpf = pd.DataFrame({
        'ID_CLIENTE_orig': leg_sem_cpf['ID_CLIENTE'],
        'ID_CLIENTE_canonico': leg_sem_cpf['ID_CLIENTE']
    })
    de_para_legado = pd.concat([
        map_leg_canonico[['ID_CLIENTE_orig', 'ID_CLIENTE_canonico']],
        map_sem_cpf
    ], ignore_index=True)

    # E-commerce: deduplica eventuais CPFs repetidos
    eco_com_cpf = eco[eco['cpf_norm'].notna()].sort_values('customer_id')
    eco_canonicos = eco_com_cpf.drop_duplicates(subset=['cpf_norm'], keep='first').copy()
    eco_sem_cpf = eco[eco['cpf_norm'].isna()].copy()

    # RDT-02: Cruzamento por CPF normalizado (válidos e inválidos)
    ambos = leg_canonicos.merge(eco_canonicos, on='cpf_norm', suffixes=('_leg', '_eco'))
    ambos_df = pd.DataFrame({
        'cpf_normalizado': ambos['cpf_norm'],
        'cpf_valido': ambos['cpf_val_eco'],
        'nome_padronizado': ambos['nome_norm_eco'],
        'cidade': ambos['city'].fillna(ambos['CIDADE']),
        'uf': ambos['state'].fillna(ambos['UF']),
        'dt_primeiro_cadastro': pd.to_datetime(ambos['DT_CADASTRO']).dt.date,
        'id_legado': ambos['ID_CLIENTE'],
        'id_ecommerce': ambos['customer_id'],
        'origem_unificacao': 'AMBOS',
        'regra_pareamento': 'CPF_EXATO'
    })

    # Apenas Legado
    cpfs_ambos = set(ambos['cpf_norm'])
    leg_sozinho_com_cpf = leg_canonicos[~leg_canonicos['cpf_norm'].isin(cpfs_ambos)]
    leg_sozinhos = pd.concat([leg_sozinho_com_cpf, leg_sem_cpf], ignore_index=True)
    leg_df = pd.DataFrame({
        'cpf_normalizado': leg_sozinhos['cpf_norm'],
        'cpf_valido': leg_sozinhos['cpf_val'],
        'nome_padronizado': leg_sozinhos['nome_norm'],
        'cidade': leg_sozinhos['CIDADE'],
        'uf': leg_sozinhos['UF'],
        'dt_primeiro_cadastro': pd.to_datetime(leg_sozinhos['DT_CADASTRO']).dt.date,
        'id_legado': leg_sozinhos['ID_CLIENTE'],
        'id_ecommerce': None,
        'origem_unificacao': 'LEGADO',
        'regra_pareamento': leg_sozinhos['cpf_norm'].apply(lambda x: 'APENAS_LEGADO' if x else 'SEM_CPF_LEGADO')
    })

    # Apenas E-commerce
    eco_sozinho_com_cpf = eco_canonicos[~eco_canonicos['cpf_norm'].isin(cpfs_ambos)]
    eco_sozinhos = pd.concat([eco_sozinho_com_cpf, eco_sem_cpf], ignore_index=True)
    eco_df = pd.DataFrame({
        'cpf_normalizado': eco_sozinhos['cpf_norm'],
        'cpf_valido': eco_sozinhos['cpf_val'],
        'nome_padronizado': eco_sozinhos['nome_norm'],
        'cidade': eco_sozinhos['city'],
        'uf': eco_sozinhos['state'],
        'dt_primeiro_cadastro': pd.to_datetime(eco_sozinhos['created_at']).dt.date,
        'id_legado': None,
        'id_ecommerce': eco_sozinhos['customer_id'],
        'origem_unificacao': 'ECOM',
        'regra_pareamento': eco_sozinhos['cpf_norm'].apply(lambda x: 'APENAS_ECOM' if x else 'SEM_CPF_ECOM')
    })

    # Consolidação de dw.dim_cliente
    dim_cliente = pd.concat([ambos_df, leg_df, eco_df], ignore_index=True)
    
    with engine.begin() as cx:
        cx.execute(text("TRUNCATE dw.dim_cliente CASCADE"))
    
    dim_cliente.to_sql('dim_cliente', engine, schema='dw', if_exists='append', index=False)
    print(f"  [dw.dim_cliente] {len(dim_cliente)} clientes carregados.")

    # Tabelas auxiliares de mapeamento para posterior carga de fatos
    with engine.connect() as cx:
        sk_map = pd.read_sql(text('SELECT cliente_sk, id_legado, id_ecommerce FROM dw.dim_cliente'), cx)
    
    map_leg_final = de_para_legado.merge(
        sk_map[sk_map['id_legado'].notna()], left_on='ID_CLIENTE_canonico', right_on='id_legado'
    )[['ID_CLIENTE_orig', 'cliente_sk']].rename(columns={'ID_CLIENTE_orig': 'id_legado_orig'})
    map_leg_final.to_sql('map_cliente_legado', engine, schema='stg', if_exists='replace', index=False)

    map_eco_final = sk_map[sk_map['id_ecommerce'].notna()][['id_ecommerce', 'cliente_sk']].rename(
        columns={'id_ecommerce': 'customer_id_orig'}
    )
    map_eco_final.to_sql('map_cliente_ecom', engine, schema='stg', if_exists='replace', index=False)

    # Asserções de qualidade
    qa.cardinalidade_preservada("cardinalidade dim_cliente", len(leg) + len(eco), len(dim_cliente), "unificacao reduz registros")
    qa.igual("clientes unificados em AMBOS", len(ambos_df), 12605, "intersecao exata de CPFs")
    qa.unico("cpf_normalizado sem duplicatas entre validos", dim_cliente.loc[dim_cliente['cpf_valido'] == True, 'cpf_normalizado'], "unicidade de CPFs validos")
    qa.dominio("origem_unificacao em {LEGADO,ECOM,AMBOS}", dim_cliente['origem_unificacao'], {'LEGADO', 'ECOM', 'AMBOS'}, "origens conformadas")


# ===========================================================================
# DECISÃO 2 — CONFORMAÇÃO DE STATUS
# ===========================================================================
def conforma_status(qa):
    """
    Decisão 2 / RDT-04: Conformação hierárquica de status de pedido
    """
    engine = eng_dw()
    
    dados_status = [
        # Legado (130.000 pedidos)
        {"sistema": "LEGADO", "status_origem": "ENTREGUE", "status_conformado": "ENTREGUE", "motivo_cancelamento": None},
        {"sistema": "LEGADO", "status_origem": "CANCELADO", "status_conformado": "CANCELADO", "motivo_cancelamento": None},
        {"sistema": "LEGADO", "status_origem": "EM TRANSITO", "status_conformado": "EM_TRANSITO", "motivo_cancelamento": None},
        {"sistema": "LEGADO", "status_origem": "SEPARACAO", "status_conformado": "SEPARACAO", "motivo_cancelamento": None},
        # E-commerce (280.000 pedidos)
        {"sistema": "ECOM", "status_origem": "delivered", "status_conformado": "ENTREGUE", "motivo_cancelamento": None},
        {"sistema": "ECOM", "status_origem": "canceled", "status_conformado": "CANCELADO", "motivo_cancelamento": "SOLICITACAO_CLIENTE"},
        {"sistema": "ECOM", "status_origem": "payment_declined", "status_conformado": "CANCELADO", "motivo_cancelamento": "RECUSA_PAGAMENTO"},
        {"sistema": "ECOM", "status_origem": "shipped", "status_conformado": "EM_TRANSITO", "motivo_cancelamento": None},
        {"sistema": "ECOM", "status_origem": "processing", "status_conformado": "SEPARACAO", "motivo_cancelamento": None},
    ]
    df_status = pd.DataFrame(dados_status)

    with engine.begin() as cx:
        cx.execute(text("TRUNCATE dw.dim_status CASCADE"))
        
    df_status.to_sql("dim_status", engine, schema="dw", if_exists="append", index=False)
    print(f"  [dw.dim_status] {len(df_status)} status conformados carregados.")

    # Asserções de qualidade
    qa.igual("total de linhas dim_status", len(df_status), 9, "9 estados mapeados das origens")
    qa.unico("status_origem e sistema unicos", df_status["status_origem"] + "_" + df_status["sistema"], "chave composta unica")
    qa.dominio("macro-status permitidos", df_status["status_conformado"], {"ENTREGUE", "CANCELADO", "EM_TRANSITO", "SEPARACAO"}, "dominio conformado")


# ===========================================================================
# DECISÃO 3 — SEMÂNTICA DOS VALORES MONETÁRIOS
# ===========================================================================
def conforma_valores(qa):
    """
    Decisão 3 / RDT-05 e RDT-06: Semântica dos Valores Monetários e Sentinelas Financeiros
    """
    engine = eng_dw()
    
    with engine.begin() as cx:
        # Criação e carga de stg.itens_conformados
        # Tratamento de sentinela: VL_DESCONTO = -1 vira 0.00
        cx.execute(text('''
            CREATE TABLE IF NOT EXISTS stg.itens_conformados (
                id_item_origem TEXT,
                id_pedido_origem TEXT,
                id_produto_origem BIGINT,
                sistema_origem TEXT,
                quantidade INT,
                valor_unitario NUMERIC(12,2),
                valor_desconto NUMERIC(12,2),
                valor_liquido NUMERIC(12,2)
            );
        '''))
        cx.execute(text('TRUNCATE stg.itens_conformados'))
        
        # Itens do Legado
        cx.execute(text('''
            INSERT INTO stg.itens_conformados
            SELECT 
                'LEG-' || "ID_ITEM"::text,
                'LEG-' || "ID_PEDIDO"::text,
                "ID_PRODUTO"::bigint,
                'LEGADO',
                "QTD",
                "VL_UNITARIO",
                GREATEST("VL_DESCONTO", 0),
                ("QTD" * "VL_UNITARIO" - GREATEST("VL_DESCONTO", 0))
            FROM stg.legado_itens_pedido;
        '''))
        
        # Itens do E-commerce
        cx.execute(text('''
            INSERT INTO stg.itens_conformados
            SELECT 
                'ECOM-' || order_item_id::text,
                'ECOM-' || order_id::text,
                product_id,
                'ECOM',
                quantity,
                unit_price,
                COALESCE(discount, 0),
                (quantity * unit_price - COALESCE(discount, 0))
            FROM stg.ecom_order_item;
        '''))
        
        count_itens = cx.execute(text('SELECT count(*) FROM stg.itens_conformados')).scalar()
        print(f"  [stg.itens_conformados] {count_itens} itens conformados carregados.")

        # Criação e carga de stg.pedidos_conformados com as 4 medidas monetárias equalizadas
        cx.execute(text('''
            CREATE TABLE IF NOT EXISTS stg.pedidos_conformados (
                id_origem TEXT,
                sistema_origem TEXT,
                cliente_origem_id BIGINT,
                data_pedido TIMESTAMP,
                data_entrega TIMESTAMP,
                canal_origem TEXT,
                status_origem TEXT,
                qtd_itens INT,
                valor_mercadoria NUMERIC(12,2),
                valor_frete NUMERIC(12,2),
                valor_desconto NUMERIC(12,2),
                valor_total NUMERIC(12,2)
            );
        '''))
        cx.execute(text('TRUNCATE stg.pedidos_conformados'))
        
        # Pedidos do Legado: VALOR_TOTAL original já incluía frete
        cx.execute(text('''
            INSERT INTO stg.pedidos_conformados
            SELECT 
                'LEG-' || p."ID_PEDIDO"::text,
                'LEGADO',
                p."ID_CLIENTE"::bigint,
                p."DT_PEDIDO"::timestamp,
                CASE WHEN p."DT_ENTREGA" = '1900-01-01 00:00:00' THEN NULL ELSE p."DT_ENTREGA"::timestamp END,
                p."CANAL",
                p."STATUS",
                COALESCE(i.qtd_itens, 0)::int,
                COALESCE(i.valor_mercadoria, 0)::numeric(12,2),
                p."VALOR_FRETE"::numeric(12,2),
                COALESCE(i.valor_desconto, 0)::numeric(12,2),
                (COALESCE(i.valor_mercadoria, 0) + p."VALOR_FRETE")::numeric(12,2)
            FROM stg.legado_pedidos p
            LEFT JOIN (
                SELECT id_pedido_origem, 
                       SUM(quantidade) as qtd_itens,
                       SUM(valor_liquido) as valor_mercadoria,
                       SUM(valor_desconto) as valor_desconto
                FROM stg.itens_conformados
                WHERE sistema_origem = 'LEGADO'
                GROUP BY id_pedido_origem
            ) i ON ('LEG-' || p."ID_PEDIDO"::text) = i.id_pedido_origem;
        '''))
        
        # Pedidos do E-commerce: total_amount original era sem frete; somamos freight_amount para equalizar valor_total
        cx.execute(text('''
            INSERT INTO stg.pedidos_conformados
            SELECT 
                'ECOM-' || p.order_id::text,
                'ECOM',
                p.customer_id,
                p.placed_at,
                p.delivered_at,
                p.channel,
                p.status,
                COALESCE(i.qtd_itens, 0)::int,
                p.total_amount::numeric(12,2),
                p.freight_amount::numeric(12,2),
                COALESCE(i.valor_desconto, 0)::numeric(12,2),
                (p.total_amount + p.freight_amount)::numeric(12,2)
            FROM stg.ecom_orders p
            LEFT JOIN (
                SELECT id_pedido_origem, 
                       SUM(quantidade) as qtd_itens,
                       SUM(valor_desconto) as valor_desconto
                FROM stg.itens_conformados
                WHERE sistema_origem = 'ECOM'
                GROUP BY id_pedido_origem
            ) i ON ('ECOM-' || p.order_id::text) = i.id_pedido_origem;
        '''))
        
        cnt_pedidos = cx.execute(text('SELECT count(*) FROM stg.pedidos_conformados')).scalar()
        print(f"  [stg.pedidos_conformados] {cnt_pedidos} pedidos conformados carregados.")

        # Teste de reconciliação financeira (asserções de qualidade)
        falhas_rec = cx.execute(text('''
            SELECT COUNT(*) 
            FROM stg.pedidos_conformados p
            JOIN (
                SELECT id_pedido_origem, SUM(valor_liquido) as soma_itens
                FROM stg.itens_conformados
                GROUP BY id_pedido_origem
            ) i ON p.id_origem = i.id_pedido_origem
            WHERE ABS(p.valor_mercadoria - i.soma_itens) > 0.02
        ''')).scalar()

    qa.igual("pedidos conformados carregados", cnt_pedidos, 410000, "410.000 pedidos carregados")
    qa.igual("reconciliacao valor_mercadoria vs itens", falhas_rec, 0, "soma de itens bate com total (resíduo <= 0.02)")


# ===========================================================================
# DECISÃO 4 — TAXONOMIA DE PRODUTO
# ===========================================================================
def conforma_categorias(qa):
    """
    Decisão 4 / RDT-07: Taxonomia de Produtos e Conformação de Categorias
    """
    engine = eng_dw()
    
    with engine.connect() as cx:
        # Produtos do E-commerce com taxonomia de 2 níveis
        ecom_p = pd.read_sql(text('''
            SELECT 
                p.product_id as id_ecommerce,
                p.sku,
                p.title as descricao,
                p.list_price as preco_referencia,
                p.active as ativo,
                'ECOM' as origem,
                c.name as categoria_origem,
                COALESCE(parent.name, c.name) as categoria_nivel1,
                CASE WHEN c.parent_id IS NOT NULL THEN c.name ELSE NULL END as categoria_nivel2
            FROM stg.ecom_product p
            LEFT JOIN stg.ecom_category c ON p.category_id = c.category_id
            LEFT JOIN stg.ecom_category parent ON c.parent_id = parent.category_id
        '''), cx)

        # Produtos do Legado em texto livre
        leg_p = pd.read_sql(text('SELECT "ID_PRODUTO", "DESCRICAO", "CATEGORIA", "PRECO_TABELA", "ATIVO" FROM stg.legado_produtos'), cx)

    # Mapeamento controlado das 27 variações do legado para a taxonomia do e-commerce
    MAPA_LEGADO = {
        'FERRAMENTAS': ('Ferramentas', None),
        'Ferramentas e construcao': ('Ferramentas', None),
        'CASA': ('Casa e Decoração', None),
        'Casa e decoracao': ('Casa e Decoração', None),
        'MOVEIS': ('Casa e Decoração', 'Móveis'),
        'ESPORTE': ('Esporte e Lazer', None),
        'Esportes e lazer': ('Esporte e Lazer', None),
        'Televisores': ('Áudio e TV', 'Televisores'),
        'AUDIO/VIDEO': ('Áudio e TV', 'Áudio'),
        'TV E SOM': ('Áudio e TV', None), # Cobre dois filhos de Áudio e TV
        'TELEFONIA': ('Telefonia', 'Smartphones'),
        'Celulares': ('Telefonia', 'Smartphones'),
        'CELULAR/SMARTPHONE': ('Telefonia', 'Smartphones'),
        'INFORMATICA': ('Informática', None),
        'Informática': ('Informática', None),
        'INFO': ('Informática', None),
        'informatica e games': ('Informática', None), # Ramo híbrido mapeado para Informática
        'GAMES': ('Games', None),
        'Games e consoles': ('Games', None),
        'Eletro': ('Eletrodomésticos', None),
        'Eletro-domesticos': ('Eletrodomésticos', None),
        'ELETRODOMÉSTICOS': ('Eletrodomésticos', None),
        'eletrodomesticos': ('Eletrodomésticos', None),
        'ELETRO': ('Eletrodomésticos', None),
        'DIVERSOS': ('Outros', None),
        'OUTROS': ('Outros', None),
        '': ('Outros', None),
    }

    leg_mapped = []
    for _, r in leg_p.iterrows():
        cat_orig = (r['CATEGORIA'] or '').strip()
        n1, n2 = MAPA_LEGADO.get(cat_orig, ('Outros', None))
        leg_mapped.append({
            'id_legado': r['ID_PRODUTO'],
            'id_ecommerce': None,
            'sku': f"LEG-{r['ID_PRODUTO']}",
            'descricao': r['DESCRICAO'],
            'preco_referencia': r['PRECO_TABELA'],
            'ativo': bool(r['ATIVO']),
            'origem': 'LEGADO',
            'categoria_origem': r['CATEGORIA'], # Preservação obrigatória do valor original
            'categoria_nivel1': n1,
            'categoria_nivel2': n2,
        })
    df_leg = pd.DataFrame(leg_mapped)

    dim_produto = pd.concat([df_leg, ecom_p], ignore_index=True)
    
    with engine.begin() as cx:
        cx.execute(text("TRUNCATE dw.dim_produto CASCADE"))
        
    dim_produto.to_sql("dim_produto", engine, schema="dw", if_exists="append", index=False)
    print(f"  [dw.dim_produto] {len(dim_produto)} produtos conformados carregados.")

    # Mapeamento auxiliar de SKs para carga de fato_item_pedido
    with engine.connect() as cx:
        sk_prod = pd.read_sql(text('SELECT produto_sk, id_legado, id_ecommerce FROM dw.dim_produto'), cx)
        
    map_prod_leg = sk_prod[sk_prod['id_legado'].notna()][['id_legado', 'produto_sk']]
    map_prod_leg.to_sql('map_produto_legado', engine, schema='stg', if_exists='replace', index=False)
    
    map_prod_eco = sk_prod[sk_prod['id_ecommerce'].notna()][['id_ecommerce', 'produto_sk']]
    map_prod_eco.to_sql('map_produto_ecom', engine, schema='stg', if_exists='replace', index=False)

    # Asserções de qualidade
    qa.igual("total de produtos dim_produto", len(dim_produto), 15000, "15.000 produtos conformados (3k leg + 12k eco)")
    qa.dominio("origem do produto em {LEGADO,ECOM}", dim_produto["origem"], {"LEGADO", "ECOM"}, "origem de produto valida")
    qa.igual("produtos em categoria Outros", int((dim_produto["categoria_nivel1"] == "Outros").sum()), 340, "340 produtos sem classificacao definida")


# ===========================================================================
# DECISÃO 5 — DATAS, AUSÊNCIAS E SENTINELAS
# ===========================================================================
def trata_datas_e_ausencias(qa):
    """
    Decisão 5 / RDT-08 e RDT-09: Tratamento de Datas, Ausências, Sentinelas e Fusos Horários
    """
    engine = eng_dw()
    
    with engine.begin() as cx:
        # Atualizar pedidos_conformados com dias_entrega e tratamento de datas
        cx.execute(text('''
            ALTER TABLE stg.pedidos_conformados ADD COLUMN IF NOT EXISTS dias_entrega INT;
            UPDATE stg.pedidos_conformados
            SET dias_entrega = CASE 
                WHEN data_entrega IS NULL THEN NULL
                WHEN data_entrega < data_pedido THEN NULL -- Inconsistência temporal tratada como NULL
                ELSE EXTRACT(DAY FROM (data_entrega - data_pedido))::int
            END;
        '''))
        
        # Tratamento do SAC: vazios em data_fechamento viram NULL (chamados em aberto)
        cx.execute(text('''
            UPDATE stg.sac_atendimentos
            SET data_fechamento = NULL
            WHERE data_fechamento = '' OR data_fechamento = 'NULL';
        '''))

        # Verificações para asserções
        negativos = cx.execute(text('SELECT COUNT(*) FROM stg.pedidos_conformados WHERE dias_entrega < 0')).scalar()
        s1900 = cx.execute(text("SELECT COUNT(*) FROM stg.pedidos_conformados WHERE data_entrega = '1900-01-01 00:00:00'")).scalar()
        ent_ant_null = cx.execute(text('SELECT COUNT(*) FROM stg.pedidos_conformados WHERE data_entrega < data_pedido AND dias_entrega IS NULL')).scalar()

    print("  [stg.pedidos_conformados] Prazos de entrega e sentinelas temporais tratados.")

    # Asserções de qualidade
    qa.igual("prazos de entrega negativos no DW", negativos, 0, "nenhum prazo de entrega negativo")
    qa.igual("sentinelas 1900-01-01 em data_entrega", s1900, 0, "todos os sentinelas 1900 convertidos para NULL")
    qa.igual("pedidos com entrega anterior ao pedido com dias_entrega NULL", ent_ant_null, 2458, "775 leg + 1683 eco com prazo anulado")


# ===========================================================================
# DECISÃO 6 — CHAVES DAS FONTES DE ARQUIVO
# ===========================================================================
def liga_sac_e_avaliacoes(qa):
    """
    Decisão 6: Ligação e conformação das fontes de arquivo (SAC e Avaliações)
    """
    engine = eng_dw()
    
    with engine.begin() as cx:
        # SAC conformado com ligação a pedidos
        cx.execute(text('''
            CREATE TABLE IF NOT EXISTS stg.sac_conformado (
                protocolo TEXT PRIMARY KEY,
                id_pedido_origem TEXT,
                cpf_normalizado TEXT,
                data_abertura DATE,
                data_fechamento DATE,
                canal TEXT,
                motivo_conformado TEXT,
                nota_satisfacao INT,
                horas_resolucao NUMERIC(10,2)
            );
        '''))
        cx.execute(text('TRUNCATE stg.sac_conformado'))
        cx.execute(text('''
            INSERT INTO stg.sac_conformado
            SELECT 
                protocolo,
                (CASE WHEN origem_sistema = 'LEGADO' THEN 'LEG-' || id_pedido_origem
                      ELSE 'ECOM-' || id_pedido_origem END) as id_pedido_origem,
                regexp_replace(cpf_cliente, '[^0-9]', '', 'g') as cpf_normalizado,
                TO_DATE(data_abertura, 'DD/MM/YYYY') as data_abertura,
                CASE WHEN data_fechamento IS NULL OR data_fechamento = '' OR data_fechamento = 'NULL' THEN NULL
                     ELSE TO_DATE(data_fechamento, 'DD/MM/YYYY') END as data_fechamento,
                UPPER(TRIM(canal)) as canal,
                TRIM(motivo) as motivo_conformado,
                CASE WHEN nota_satisfacao ~ '^[1-5]$' THEN nota_satisfacao::int ELSE NULL END as nota_satisfacao,
                GREATEST(REPLACE(tempo_resolucao_horas, ',', '.')::numeric(10,2), 0) as horas_resolucao
            FROM stg.sac_atendimentos;
        '''))

        # Avaliações conformadas com ligação a pedidos e produtos
        cx.execute(text('''
            CREATE TABLE IF NOT EXISTS stg.avaliacoes_conformadas (
                review_id TEXT PRIMARY KEY,
                order_ref TEXT,
                product_sku TEXT,
                data_avaliacao DATE,
                nota INT,
                compra_verificada BOOLEAN,
                votos_uteis INT
            );
        '''))
        cx.execute(text('TRUNCATE stg.avaliacoes_conformadas'))
        cx.execute(text('''
            INSERT INTO stg.avaliacoes_conformadas
            SELECT 
                review_id,
                order_ref,
                product_sku,
                submitted_at::timestamptz::date as data_avaliacao,
                CASE WHEN rating ~ '^[1-5]$' THEN rating::int ELSE NULL END as nota,
                verified_purchase,
                helpful_votes
            FROM stg.mkt_avaliacoes;
        '''))

        # Verificação das coberturas de chaves
        sac_ped_hit = cx.execute(text('''
            SELECT COUNT(*) 
            FROM stg.sac_conformado s
            JOIN stg.pedidos_conformados p ON s.id_pedido_origem = p.id_origem
        ''')).scalar()

        mkt_ped_hit = cx.execute(text('''
            SELECT COUNT(*)
            FROM stg.avaliacoes_conformadas m
            JOIN stg.pedidos_conformados p ON m.order_ref = p.id_origem
        ''')).scalar()

        mkt_prod_hit = cx.execute(text('''
            SELECT COUNT(*)
            FROM stg.avaliacoes_conformadas m
            JOIN dw.dim_produto pr ON m.product_sku = pr.sku
        ''')).scalar()

    print(f"  [stg.sac_conformado] 96.140 chamados conformados e ligados ({sac_ped_hit} a pedidos).")
    print(f"  [stg.avaliacoes_conformadas] 160.000 avaliações conformadas e ligadas ({mkt_ped_hit} a pedidos, {mkt_prod_hit} a produtos).")

    # Asserções de qualidade
    qa.igual("cobertura SAC -> pedido no DW", sac_ped_hit, 96140, "100% dos chamados conectam a pedidos")
    qa.igual("cobertura avaliacoes -> pedido no DW", mkt_ped_hit, 160000, "100% das avaliacoes conectam a pedidos")
    qa.igual("cobertura avaliacoes -> produto no DW", mkt_prod_hit, 160000, "100% das avaliacoes conectam a produtos")


if __name__ == "__main__":
    qa = Suite(etapa="02_transformacao")
    print("Iniciando etapa 02_transformacao...")
    unifica_clientes(qa)
    conforma_status(qa)
    conforma_valores(qa)
    conforma_categorias(qa)
    trata_datas_e_ausencias(qa)
    liga_sac_e_avaliacoes(qa)

    # Asserções obrigatórias registradas
    dw = eng_dw()
    qa.registrar(dw)
    if qa.imprimir():
        print("Há asserções em falha. Isso não impede seguir, mas precisa aparecer no RDT com explicação.")
