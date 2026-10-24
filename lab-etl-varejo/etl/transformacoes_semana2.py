"""Conformação da Semana 2. stg é somente leitura; resultados derivados em cfm."""
import re
import unicodedata
from collections import Counter
from datetime import date
import pandas as pd

from sqlalchemy import MetaData, Table, text
from config import DATA_CORTE
from semana2_utils import LOTE, escalar, verifica_sql

# Hipótese explícita para horários sem fuso; o dia de negócio usa a mesma zona.
FUSO_NEGOCIO = 'America/Sao_Paulo'


def normaliza_nome(nome):
    n = unicodedata.normalize('NFD', (nome or '').strip().upper())
    return ' '.join(''.join(c for c in n if unicodedata.category(c) != 'Mn').split())


def so_digitos(valor):
    return re.sub(r'\D', '', valor or '')


def cpf_valido(valor):
    if not valor or len(valor) != 11: return None
    if len(set(valor)) == 1: return False
    for n in (9, 10):
        d = sum(int(valor[i]) * (n + 1 - i) for i in range(n)) * 10 % 11
        if int(valor[n]) != (0 if d == 10 else d): return False
    return True


def insere(cx, schema, nome, linhas):
    tab = Table(nome, MetaData(), schema=schema, autoload_with=cx)
    for ini in range(0, len(linhas), LOTE):
        cx.execute(tab.insert(), linhas[ini:ini + LOTE])


def prepara(cx):
    # Impede a reconstrução de dimensões referenciadas por fatos ou ABT carregados.
    fatos = ['dw.fato_pedido', 'dw.fato_item_pedido', 'dw.fato_atendimento',
             'dw.fato_avaliacao', 'abt.recompra_90d']
    if any(escalar(cx, f'SELECT EXISTS(SELECT 1 FROM {t})') for t in fatos):
        raise RuntimeError('Há fatos/ABT preenchidos: execute a Semana 2 em um DW vazio ou cópia isolada.')
    cx.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    cx.execute(text('CREATE SCHEMA IF NOT EXISTS cfm'))
    # Apenas tabelas derivadas próprias; nenhuma tabela stg é alterada.
    for nome in ['map_cliente_legado', 'map_cliente_ecom', 'clientes_origem',
                 'map_produto_legado', 'map_produto_ecom', 'produtos_auditoria',
                 'itens_conformados', 'pedidos_conformados', 'sac_conformado',
                 'avaliacoes_conformadas', 'inventario_ausencias']:
        cx.execute(text(f'DROP TABLE IF EXISTS cfm.{nome}'))
    cx.execute(text('TRUNCATE dw.dim_cliente, dw.dim_produto, dw.dim_status RESTART IDENTITY CASCADE'))


def unifica_clientes(qa, cx, m):
    leg = [dict(r) for r in cx.execute(text('SELECT * FROM stg.legado_clientes ORDER BY "ID_CLIENTE"')).mappings()]
    eco = [dict(r) for r in cx.execute(text('SELECT * FROM stg.ecom_customer ORDER BY customer_id')).mappings()]
    grupos = {}
    origem = []
    for sistema, rows in [('LEGADO', leg), ('ECOM', eco)]:
        for r in rows:
            legado = sistema == 'LEGADO'
            ident = int(r['ID_CLIENTE'] if legado else r['customer_id'])
            cpf = so_digitos(r['CPF'] if legado else r['tax_id'])
            cpf = cpf if len(cpf) == 11 else None
            cidade = r['CIDADE'] if legado else r['city']
            cidade_sentinela = (cidade or '').strip().upper() == 'N/A'
            cidade = None if not (cidade or '').strip() or cidade_sentinela else cidade.strip()
            cadastro = r['DT_CADASTRO'] if legado else r['created_at']
            if hasattr(cadastro, 'hour'):
                # Usa o dia civil do cadastro, não o dia UTC da ingestão.
                from zoneinfo import ZoneInfo
                cadastro = cadastro.astimezone(ZoneInfo(FUSO_NEGOCIO)).date()
            row = dict(sistema=sistema, id_origem=ident, cpf_normalizado=cpf,
                       cpf_valido=cpf_valido(cpf), nome=normaliza_nome(r['NOME'] if legado else r['full_name']),
                       cidade=cidade, uf=r['UF'] if legado else r['state'], cadastro=cadastro,
                       cpf_ausente=cpf is None, cidade_sentinela=cidade_sentinela)
            chave = 'CPF:' + cpf if cpf else f'{sistema}:{ident:012}'
            grupos.setdefault(chave, []).append(row)
            origem.append(row)
    dimensao, mapa = [], []
    for sk, chave in enumerate(sorted(grupos), 1):
        grupo = grupos[chave]
        a = sorted([r for r in grupo if r['sistema'] == 'LEGADO'], key=lambda r: r['id_origem'])
        b = sorted([r for r in grupo if r['sistema'] == 'ECOM'], key=lambda r: r['id_origem'])
        canonico = (b or a)[0]
        procedencia = 'AMBOS' if a and b else canonico['sistema']
        regra = 'CPF_EXATO' if a and b else ('APENAS_' if canonico['cpf_normalizado'] else 'SEM_CPF_') + procedencia
        cidades = [r['cidade'] for r in ([canonico] + a + b) if r['cidade']]
        datas = [r['cadastro'] for r in grupo if r['cadastro']]
        dimensao.append(dict(cliente_sk=sk, cpf_normalizado=canonico['cpf_normalizado'],
                             cpf_valido=canonico['cpf_valido'], nome_padronizado=canonico['nome'],
                             cidade=cidades[0] if cidades else None, uf=canonico['uf'],
                             dt_primeiro_cadastro=min(datas) if datas else None,
                             id_legado=a[0]['id_origem'] if a else None,
                             id_ecommerce=b[0]['id_origem'] if b else None,
                             origem_unificacao=procedencia, regra_pareamento=regra))
        for row in grupo:
            mapa.append(dict(sistema=row['sistema'], id_origem=row['id_origem'], cliente_sk=sk,
                             cpf_normalizado=row['cpf_normalizado'], cpf_valido=row['cpf_valido'],
                             cpf_ausente=row['cpf_ausente'], cidade_sentinela=row['cidade_sentinela'],
                             id_canonico=(a if row['sistema'] == 'LEGADO' else b)[0]['id_origem']))
    insere(cx, 'dw', 'dim_cliente', dimensao)
    cx.execute(text("SELECT setval(pg_get_serial_sequence('dw.dim_cliente','cliente_sk'), (SELECT MAX(cliente_sk) FROM dw.dim_cliente))"))
    cx.execute(text('''CREATE TABLE cfm.clientes_origem (
        sistema TEXT, id_origem BIGINT, cliente_sk BIGINT NOT NULL,
        cpf_normalizado CHAR(11), cpf_valido BOOLEAN, cpf_ausente BOOLEAN,
        cidade_sentinela BOOLEAN, id_canonico BIGINT, PRIMARY KEY(sistema,id_origem))'''))
    insere(cx, 'cfm', 'clientes_origem', mapa)
    cx.execute(text("CREATE TABLE cfm.map_cliente_legado AS SELECT id_origem AS id_legado_orig, cliente_sk FROM cfm.clientes_origem WHERE sistema='LEGADO'"))
    cx.execute(text("CREATE TABLE cfm.map_cliente_ecom AS SELECT id_origem AS customer_id_orig, cliente_sk FROM cfm.clientes_origem WHERE sistema='ECOM'"))
    m['clientes'] = dict(brutos_legado=len(leg), brutos_ecom=len(eco), total=len(dimensao),
                         por_origem=dict(Counter(d['origem_unificacao'] for d in dimensao)),
                         por_sistema={s: dict(registros=sum(r['sistema']==s for r in mapa),
                             colapsados=sum(r['sistema']==s and r['id_origem']!=r['id_canonico'] for r in mapa),
                             cpf_ausente=sum(r['sistema']==s and r['cpf_ausente'] for r in mapa),
                             cpf_invalido=sum(r['sistema']==s and r['cpf_valido'] is False for r in mapa),
                             cidade_sentinela=sum(r['sistema']==s and r['cidade_sentinela'] for r in mapa)) for s in ['LEGADO','ECOM']})
    qa.igual('mapa completo clientes legado', escalar(cx,'SELECT count(*) FROM cfm.map_cliente_legado'), len(leg))
    qa.igual('mapa completo clientes ecommerce', escalar(cx,'SELECT count(*) FROM cfm.map_cliente_ecom'), len(eco))
    qa.unico('cpf sem duplicatas entre validos', pd.Series([d['cpf_normalizado'] for d in dimensao if d['cpf_valido'] is True],dtype=object))
    qa.unico('cpf sem duplicatas entre invalidos', pd.Series([d['cpf_normalizado'] for d in dimensao if d['cpf_valido'] is False],dtype=object))
    qa.cardinalidade_preservada('cardinalidade clientes', len(leg)+len(eco), len(dimensao))
    qa.dominio('origem unificacao', pd.Series([d['origem_unificacao'] for d in dimensao],dtype=object), {'LEGADO','ECOM','AMBOS'})
    verifica_sql(qa,cx,'pedidos sem mapa de cliente', '''SELECT
        (SELECT count(*) FROM stg.legado_pedidos p LEFT JOIN cfm.map_cliente_legado m ON p."ID_CLIENTE"=m.id_legado_orig WHERE m.cliente_sk IS NULL)
      + (SELECT count(*) FROM stg.ecom_orders p LEFT JOIN cfm.map_cliente_ecom m ON p.customer_id=m.customer_id_orig WHERE m.cliente_sk IS NULL)''')
    m['clientes']['compartilhados_invalidos']=escalar(cx,"SELECT count(*) FROM dw.dim_cliente WHERE origem_unificacao='AMBOS' AND cpf_valido=FALSE")
    m['clientes']['pedidos_ecom_ids_colapsados']=escalar(cx,"SELECT count(*) FROM stg.ecom_orders p JOIN cfm.clientes_origem m ON m.sistema='ECOM' AND m.id_origem=p.customer_id WHERE m.id_origem<>m.id_canonico")


def conforma_status(qa, cx, m):
    cx.execute(text('''INSERT INTO dw.dim_status(status_origem,sistema,status_conformado,motivo_cancelamento) VALUES
        ('ENTREGUE','LEGADO','ENTREGUE',NULL), ('CANCELADO','LEGADO','CANCELADO',NULL),
        ('EM TRANSITO','LEGADO','EM_TRANSITO',NULL), ('SEPARACAO','LEGADO','SEPARACAO',NULL),
        ('delivered','ECOM','ENTREGUE',NULL), ('canceled','ECOM','CANCELADO','SOLICITACAO_CLIENTE'),
        ('payment_declined','ECOM','CANCELADO','RECUSA_PAGAMENTO'),
        ('shipped','ECOM','EM_TRANSITO',NULL), ('processing','ECOM','SEPARACAO',NULL)'''))
    verifica_sql(qa,cx,'status de origem sem mapeamento', '''SELECT count(*) FROM (
        SELECT 'LEGADO' sistema,"STATUS" status FROM stg.legado_pedidos
        UNION ALL SELECT 'ECOM',status FROM stg.ecom_orders) p
        LEFT JOIN dw.dim_status s ON s.sistema=p.sistema AND s.status_origem=p.status WHERE s.status_sk IS NULL''')
    qa.igual('nove status de origem', escalar(cx,'SELECT count(*) FROM dw.dim_status'),9)
    m['status']=[dict(r) for r in cx.execute(text('''SELECT p.sistema,p.status,count(*) n FROM (
        SELECT 'LEGADO' sistema,"STATUS" status FROM stg.legado_pedidos UNION ALL
        SELECT 'ECOM',status FROM stg.ecom_orders) p GROUP BY p.sistema,p.status ORDER BY 1,2''')).mappings()]


def conforma_valores(qa, cx, m):
    cx.execute(text('''CREATE TABLE cfm.itens_conformados AS
        SELECT 'LEG-'||"ID_ITEM"::text id_item_origem, 'LEG-'||"ID_PEDIDO"::text id_pedido_origem,
        "ID_PRODUTO"::bigint id_produto_origem,'LEGADO'::text sistema_origem,"QTD" quantidade,
        "VL_UNITARIO" valor_unitario,CASE WHEN "VL_DESCONTO"=-1 THEN 0 ELSE "VL_DESCONTO" END valor_desconto,
        "QTD"*"VL_UNITARIO" valor_bruto,
        "QTD"*"VL_UNITARIO"-CASE WHEN "VL_DESCONTO"=-1 THEN 0 ELSE "VL_DESCONTO" END valor_liquido,
        ("VL_DESCONTO"=-1) desconto_nao_informado
        FROM stg.legado_itens_pedido
        UNION ALL SELECT 'ECOM-'||order_item_id::text,'ECOM-'||order_id::text,product_id,'ECOM',quantity,
        unit_price,discount,quantity*unit_price,quantity*unit_price-discount,FALSE FROM stg.ecom_order_item'''))
    cx.execute(text('ALTER TABLE cfm.itens_conformados ADD PRIMARY KEY(id_item_origem)'))
    cx.execute(text('CREATE INDEX ON cfm.itens_conformados(id_pedido_origem)'))
    # Primeiro agrega os itens; o frete do cabeçalho aparece uma única vez.
    cx.execute(text('''CREATE TABLE cfm.pedidos_conformados AS
        WITH itens AS (SELECT id_pedido_origem,SUM(quantidade)::int qtd_itens,
            SUM(valor_bruto) valor_mercadoria,SUM(valor_desconto) valor_desconto
            FROM cfm.itens_conformados GROUP BY id_pedido_origem),
        origens AS (SELECT 'LEG-'||"ID_PEDIDO"::text id_origem,'LEGADO'::text sistema_origem,
            "ID_CLIENTE"::bigint cliente_origem_id,
            "DT_PEDIDO" AT TIME ZONE 'America/Sao_Paulo' data_pedido,
            CASE WHEN "DT_ENTREGA"='1900-01-01 00:00:00'::timestamp THEN NULL
                 ELSE "DT_ENTREGA" AT TIME ZONE 'America/Sao_Paulo' END data_entrega,
            ("DT_ENTREGA"='1900-01-01 00:00:00'::timestamp) entrega_sentinela,
            "CANAL" canal_origem,"STATUS" status_origem,"VALOR_TOTAL" valor_total_origem,
            "VALOR_FRETE" valor_frete FROM stg.legado_pedidos
            UNION ALL SELECT 'ECOM-'||order_id::text,'ECOM',customer_id,placed_at,delivered_at,FALSE,
                channel,status,total_amount,freight_amount FROM stg.ecom_orders)
        SELECT p.*,m.cliente_sk,s.status_sk,s.status_conformado,
            i.qtd_itens,i.valor_mercadoria,i.valor_desconto,
            (i.valor_mercadoria+p.valor_frete-i.valor_desconto)::numeric(16,2) valor_total
        FROM origens p
        LEFT JOIN cfm.clientes_origem m ON m.sistema=p.sistema_origem AND m.id_origem=p.cliente_origem_id
        LEFT JOIN dw.dim_status s ON s.sistema=p.sistema_origem AND s.status_origem=p.status_origem
        LEFT JOIN itens i ON i.id_pedido_origem=p.id_origem'''))
    cx.execute(text('ALTER TABLE cfm.pedidos_conformados ADD PRIMARY KEY(id_origem)'))
    total = escalar(cx,'SELECT (SELECT count(*) FROM stg.legado_pedidos)+(SELECT count(*) FROM stg.ecom_orders)')
    qa.igual('cardinalidade pedidos preservada',escalar(cx,'SELECT count(*) FROM cfm.pedidos_conformados'),total)
    qa.igual('cardinalidade itens preservada',escalar(cx,'SELECT count(*) FROM cfm.itens_conformados'),
             escalar(cx,'SELECT (SELECT count(*) FROM stg.legado_itens_pedido)+(SELECT count(*) FROM stg.ecom_order_item)'))
    verifica_sql(qa,cx,'reconciliacao por pedido com origem', '''SELECT count(*) FROM cfm.pedidos_conformados
        WHERE valor_total IS NULL OR ABS(valor_total-(valor_total_origem+CASE WHEN sistema_origem='ECOM' THEN valor_frete ELSE 0 END))>0.01''')
    verifica_sql(qa,cx,'mercadoria bruta menos desconto igual itens liquidos', '''SELECT count(*) FROM cfm.pedidos_conformados p
        LEFT JOIN (SELECT id_pedido_origem,SUM(valor_liquido) liquido FROM cfm.itens_conformados GROUP BY 1) i ON i.id_pedido_origem=p.id_origem
        WHERE i.liquido IS NULL OR ABS(p.valor_mercadoria-p.valor_desconto-i.liquido)>0.01''')
    verifica_sql(qa,cx,'nenhum desconto sentinela conformado', "SELECT count(*) FROM cfm.itens_conformados WHERE desconto_nao_informado AND valor_desconto<>0")
    verifica_sql(qa,cx,'total igual mercadoria mais frete menos desconto', 'SELECT count(*) FROM cfm.pedidos_conformados WHERE valor_total<>valor_mercadoria+valor_frete-valor_desconto')
    verifica_sql(qa,cx,'frete preserva valor e sinal da origem', '''SELECT count(*) FROM cfm.pedidos_conformados p
        JOIN (SELECT 'LEG-'||"ID_PEDIDO"::text id,"VALOR_FRETE" frete FROM stg.legado_pedidos
              UNION ALL SELECT 'ECOM-'||order_id::text,freight_amount FROM stg.ecom_orders) o ON o.id=p.id_origem
        WHERE p.valor_frete IS DISTINCT FROM o.frete''')
    m['financeiro']=[dict(r) for r in cx.execute(text('''SELECT sistema_origem,count(*) pedidos,
        SUM(valor_total_origem) total_origem,SUM(valor_mercadoria) mercadoria_bruta,
        SUM(valor_desconto) desconto,SUM(valor_frete) frete,SUM(valor_total) total_conformado,
        COUNT(*) FILTER(WHERE valor_frete<0) fretes_negativos,
        MAX(ABS(valor_total-(valor_total_origem+CASE WHEN sistema_origem='ECOM' THEN valor_frete ELSE 0 END))) residuo_maximo
        FROM cfm.pedidos_conformados GROUP BY 1 ORDER BY 1''')).mappings()]
    m['itens'] = dict(total=escalar(cx,'SELECT count(*) FROM cfm.itens_conformados'),
        descontos_sentinela=escalar(cx,'SELECT count(*) FROM cfm.itens_conformados WHERE desconto_nao_informado'),
        pedidos_desconto_sentinela=escalar(cx,'SELECT count(DISTINCT id_pedido_origem) FROM cfm.itens_conformados WHERE desconto_nao_informado'),
        orfaos=escalar(cx,'''SELECT count(*) FROM cfm.itens_conformados i LEFT JOIN cfm.pedidos_conformados p ON p.id_origem=i.id_pedido_origem WHERE p.id_origem IS NULL'''))


def conforma_categorias(qa, cx, m):
    mapa = {
        'FERRAMENTAS': ('Ferramentas',None), 'FERRAMENTAS E CONSTRUCAO': ('Ferramentas',None),
        'CASA': ('Casa e Decoração',None), 'CASA E DECORACAO': ('Casa e Decoração',None),
        'MOVEIS': ('Casa e Decoração','Móveis'), 'ESPORTE': ('Esporte e Lazer',None),
        'ESPORTES E LAZER': ('Esporte e Lazer',None), 'TELEVISORES': ('Áudio e TV','Televisores'),
        'AUDIO/VIDEO': ('Áudio e TV',None), 'TV E SOM': ('Áudio e TV',None),
        'TELEFONIA': ('Telefonia',None), 'CELULARES': ('Telefonia','Smartphones'),
        'CELULAR/SMARTPHONE': ('Telefonia','Smartphones'), 'INFORMATICA': ('Informática',None),
        'INFO': ('Informática',None), 'INFORMATICA E GAMES': ('Informática',None),
        'GAMES': ('Games',None), 'GAMES E CONSOLES': ('Games',None),
        'ELETRO': ('Eletrodomésticos',None), 'ELETRO-DOMESTICOS': ('Eletrodomésticos',None),
        'ELETRODOMESTICOS': ('Eletrodomésticos',None), 'DIVERSOS': ('Outros',None),
        'OUTROS': ('Outros',None), '': ('Outros',None)}
    produtos = []
    for r in cx.execute(text('SELECT * FROM stg.legado_produtos ORDER BY "ID_PRODUTO"')).mappings():
        n1,n2 = mapa.get(normaliza_nome(r['CATEGORIA']), ('Outros',None))
        produtos.append(dict(id_legado=r['ID_PRODUTO'],id_ecommerce=None,sku=f"LEG-{r['ID_PRODUTO']}",
            descricao=r['DESCRICAO'],categoria_nivel1=n1,categoria_nivel2=n2,categoria_origem=r['CATEGORIA'],
            preco_referencia=r['PRECO_TABELA'],ativo={'S':True,'N':False}.get(r['ATIVO']),origem='LEGADO'))
    for r in cx.execute(text('''SELECT p.*,c.name categoria,COALESCE(pai.name,c.name) n1,
        CASE WHEN c.parent_id IS NOT NULL THEN c.name ELSE NULL END n2
        FROM stg.ecom_product p LEFT JOIN stg.ecom_category c ON p.category_id=c.category_id
        LEFT JOIN stg.ecom_category pai ON c.parent_id=pai.category_id ORDER BY p.product_id''')).mappings():
        produtos.append(dict(id_legado=None,id_ecommerce=r['product_id'],sku=r['sku'],descricao=r['title'],
            categoria_nivel1=r['n1'],categoria_nivel2=r['n2'],categoria_origem=r['categoria'],
            preco_referencia=r['list_price'],ativo=r['active'],origem='ECOM'))
    insere(cx,'dw','dim_produto',produtos)
    cx.execute(text('CREATE TABLE cfm.map_produto_legado AS SELECT id_legado,produto_sk FROM dw.dim_produto WHERE origem=\'LEGADO\''))
    cx.execute(text('CREATE TABLE cfm.map_produto_ecom AS SELECT id_ecommerce,produto_sk FROM dw.dim_produto WHERE origem=\'ECOM\''))
    cx.execute(text('''CREATE TABLE cfm.produtos_auditoria AS
        WITH medianas AS (SELECT origem,categoria_nivel1,
            percentile_cont(0.5) WITHIN GROUP(ORDER BY preco_referencia)::numeric mediana
            FROM dw.dim_produto WHERE preco_referencia>0 GROUP BY origem,categoria_nivel1)
        SELECT p.produto_sk,p.origem,p.categoria_origem,
          (p.origem='LEGADO' AND p.categoria_origem IN ('informatica e games','TV E SOM')) categoria_ambigua,
          (p.categoria_nivel1='Outros') categoria_generica,
          (p.preco_referencia>10*m.mediana) preco_suspeito,m.mediana
        FROM dw.dim_produto p LEFT JOIN medianas m ON m.origem=p.origem AND m.categoria_nivel1=p.categoria_nivel1'''))
    qa.igual('cardinalidade produtos preservada',len(produtos),escalar(cx,'SELECT (SELECT count(*) FROM stg.legado_produtos)+(SELECT count(*) FROM stg.ecom_product)'))
    verifica_sql(qa,cx,'ativo S e N corretamente mapeados', '''SELECT count(*) FROM dw.dim_produto d
        JOIN stg.legado_produtos p ON d.id_legado=p."ID_PRODUTO" WHERE d.ativo IS DISTINCT FROM CASE p."ATIVO" WHEN 'S' THEN TRUE WHEN 'N' THEN FALSE END''')
    verifica_sql(qa,cx,'categoria origem preservada', '''SELECT count(*) FROM dw.dim_produto d
        JOIN stg.legado_produtos p ON d.id_legado=p."ID_PRODUTO" WHERE d.categoria_origem IS DISTINCT FROM p."CATEGORIA"''')
    verifica_sql(qa,cx,'preco referencia preservado inclusive suspeitos', '''SELECT count(*) FROM dw.dim_produto d
        JOIN (SELECT 'LEG-'||"ID_PRODUTO"::text sku,"PRECO_TABELA" preco FROM stg.legado_produtos
              UNION ALL SELECT sku,list_price FROM stg.ecom_product) o ON o.sku=d.sku
        WHERE d.preco_referencia IS DISTINCT FROM o.preco''')
    qa.unico('sku de produto unico',pd.Series([p['sku'] for p in produtos],dtype=object))
    m['produtos']=dict(total=len(produtos),legado=sum(p['origem']=='LEGADO' for p in produtos),
        inativos_legado=sum(p['origem']=='LEGADO' and p['ativo'] is False for p in produtos),
        genericos=escalar(cx,'SELECT count(*) FROM cfm.produtos_auditoria WHERE categoria_generica'),
        ambiguos=escalar(cx,'SELECT count(*) FROM cfm.produtos_auditoria WHERE categoria_ambigua'),
        precos_suspeitos=escalar(cx,'SELECT count(*) FROM cfm.produtos_auditoria WHERE preco_suspeito'))


def trata_datas_e_ausencias(qa, cx, m):
    cx.execute(text('''ALTER TABLE cfm.pedidos_conformados
        ADD COLUMN entrega_inconsistente BOOLEAN,
        ADD COLUMN entrega_sem_data BOOLEAN,
        ADD COLUMN dias_entrega INTEGER,
        ADD COLUMN data_pedido_local DATE,
        ADD COLUMN data_entrega_local DATE'''))
    cx.execute(text('''UPDATE cfm.pedidos_conformados SET
        entrega_inconsistente=COALESCE(data_entrega<data_pedido,FALSE),
        entrega_sem_data=(status_conformado='ENTREGUE' AND data_entrega IS NULL),
        data_pedido_local=(data_pedido AT TIME ZONE 'America/Sao_Paulo')::date'''))
    cx.execute(text('''UPDATE cfm.pedidos_conformados SET data_entrega=NULL,entrega_sem_data=TRUE
        WHERE entrega_inconsistente'''))
    cx.execute(text('''UPDATE cfm.pedidos_conformados SET
        dias_entrega=floor(EXTRACT(EPOCH FROM (data_entrega-data_pedido))/86400)::int,
        data_entrega_local=(data_entrega AT TIME ZONE 'America/Sao_Paulo')::date'''))
    verifica_sql(qa,cx,'entrega valida nunca anterior ao pedido', 'SELECT count(*) FROM cfm.pedidos_conformados WHERE data_entrega<data_pedido OR dias_entrega<0')
    verifica_sql(qa,cx,'sentinela de entrega sinalizada e anulada', 'SELECT count(*) FROM cfm.pedidos_conformados WHERE entrega_sentinela AND (data_entrega IS NOT NULL OR NOT entrega_sem_data)')
    verifica_sql(qa,cx,'UTC legado representa horario local assumido', '''SELECT count(*) FROM cfm.pedidos_conformados p
        JOIN stg.legado_pedidos o ON p.id_origem='LEG-'||o."ID_PEDIDO"::text
        WHERE p.data_pedido AT TIME ZONE 'America/Sao_Paulo' IS DISTINCT FROM o."DT_PEDIDO"''')
    verifica_sql(qa,cx,'UTC ecommerce preserva instante original', '''SELECT count(*) FROM cfm.pedidos_conformados p
        JOIN stg.ecom_orders o ON p.id_origem='ECOM-'||o.order_id::text WHERE p.data_pedido IS DISTINCT FROM o.placed_at''')
    # Verifica fronteira, não apenas datas no meio do dia; não persiste dados sintéticos.
    qa.igual('fronteira do corte em horario de negocio',bool(escalar(cx,f"""SELECT
        (timestamp '{DATA_CORTE} 23:59:59' AT TIME ZONE '{FUSO_NEGOCIO}')::date = DATE '{DATA_CORTE}' + 1
        AND ((timestamp '{DATA_CORTE} 23:59:59' AT TIME ZONE '{FUSO_NEGOCIO}') AT TIME ZONE '{FUSO_NEGOCIO}')::date = DATE '{DATA_CORTE}'""")),True,
        'Guardar em UTC não desloca o dia usado no corte: consultar data_pedido_local')
    m['datas']=[dict(r) for r in cx.execute(text('''SELECT sistema_origem,count(*) total,
        count(*) FILTER(WHERE entrega_sentinela) sentinelas,
        count(*) FILTER(WHERE entrega_inconsistente) invertidas,
        count(*) FILTER(WHERE entrega_sem_data) sem_data_entrega,
        count(*) FILTER(WHERE data_pedido::date<>data_pedido_local) dia_utc_diferente
        FROM cfm.pedidos_conformados GROUP BY 1 ORDER BY 1''')).mappings()]


def liga_sac_e_avaliacoes(qa, cx, m):
    verifica_sql(qa,cx,'SAC protocolos repetidos sem conflito de conteudo', '''SELECT count(*) FROM (
        SELECT protocolo FROM stg.sac_atendimentos s GROUP BY protocolo
        HAVING count(DISTINCT (to_jsonb(s)-'_fonte'-'_extraido_em'-'_linha_origem'))>1) x''')
    cx.execute(text('''CREATE TABLE cfm.sac_conformado AS
        WITH unicos AS (SELECT DISTINCT ON(protocolo) * FROM stg.sac_atendimentos ORDER BY protocolo,_linha_origem),
        base AS (SELECT protocolo,_linha_origem,
            CASE origem_sistema WHEN 'LEGADO' THEN 'LEG-'||id_pedido_origem WHEN 'ECOM' THEN 'ECOM-'||id_pedido_origem END id_pedido_origem,
            NULLIF(regexp_replace(cpf_cliente,'[^0-9]','','g'),'') cpf_normalizado,
            to_date(data_abertura,'DD/MM/YYYY') data_abertura,
            CASE WHEN trim(data_fechamento) IN ('','NULL','N/A') THEN NULL ELSE to_date(data_fechamento,'DD/MM/YYYY') END data_fechamento,
            upper(trim(canal)) canal,upper(regexp_replace(trim(motivo),'[[:space:]]+',' ','g')) motivo_conformado,
            CASE WHEN nota_satisfacao ~ '^[1-5]$' THEN nota_satisfacao::int ELSE NULL END nota_satisfacao,
            (nota_satisfacao<>'' AND nota_satisfacao !~ '^[1-5]$') nota_invalida,
            replace(tempo_resolucao_horas,',','.')::numeric horas_originais
        FROM unicos)
        SELECT s.protocolo,s._linha_origem,s.id_pedido_origem,p.cliente_sk,s.cpf_normalizado,
            s.data_abertura,CASE WHEN s.data_fechamento<s.data_abertura THEN NULL ELSE s.data_fechamento END data_fechamento,
            (s.data_fechamento IS NULL) sem_encerramento_registrado,
            COALESCE(s.data_fechamento<s.data_abertura,FALSE) fechamento_inconsistente,
            s.canal,s.motivo_conformado,s.nota_satisfacao,s.nota_invalida,
            CASE WHEN s.horas_originais<0 THEN NULL ELSE s.horas_originais END horas_resolucao,
            (s.horas_originais<0) tempo_resolucao_invalido,
            CASE WHEN s.cpf_normalizado IS NULL OR d.cpf_normalizado IS NULL THEN NULL
                 ELSE s.cpf_normalizado=d.cpf_normalizado END cpf_confere_com_cliente_pedido
        FROM base s LEFT JOIN cfm.pedidos_conformados p ON p.id_origem=s.id_pedido_origem
        LEFT JOIN dw.dim_cliente d ON d.cliente_sk=p.cliente_sk'''))
    cx.execute(text('ALTER TABLE cfm.sac_conformado ADD PRIMARY KEY(protocolo)'))
    cx.execute(text('''CREATE TABLE cfm.avaliacoes_conformadas AS
        WITH base AS (SELECT review_id #>> '{}' review_id,_linha_origem,
            "order"->>'ref' order_ref,product->>'sku' product_sku,submitted_at #>> '{}' raw_horario,
            CASE WHEN jsonb_typeof(rating) IN ('number','string') AND (rating #>> '{}') ~ '^[1-5]$'
                 THEN (rating #>> '{}')::int ELSE NULL END nota,
            rating IS NULL rating_ausente,(rating='null'::jsonb) rating_nulo,jsonb_typeof(rating) tipo_rating_origem,
            CASE WHEN jsonb_typeof(verified_purchase)='boolean' THEN (verified_purchase #>> '{}')::boolean ELSE NULL END compra_verificada,
            CASE WHEN (helpful_votes #>> '{}') ~ '^[0-9]+$' THEN (helpful_votes #>> '{}')::int ELSE NULL END votos_uteis,
            title #>> '{}' titulo,comment #>> '{}' comentario FROM stg.mkt_avaliacoes),
        horarios AS (SELECT *,NOT(raw_horario ~ '(Z|[+-][0-9]{2}:[0-9]{2})$') fuso_assumido,
            CASE WHEN raw_horario ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN raw_horario::timestamptz
                 ELSE raw_horario::timestamp AT TIME ZONE 'America/Sao_Paulo' END data_avaliacao_utc FROM base)
        SELECT h.*, (h.data_avaliacao_utc AT TIME ZONE 'America/Sao_Paulo')::date data_avaliacao,
            p.cliente_sk,pr.produto_sk,
            EXISTS(SELECT 1 FROM cfm.itens_conformados i WHERE i.id_pedido_origem=h.order_ref
                AND ((i.sistema_origem='LEGADO' AND pr.id_legado=i.id_produto_origem)
                  OR (i.sistema_origem='ECOM' AND pr.id_ecommerce=i.id_produto_origem))) produto_consta_no_pedido
        FROM horarios h LEFT JOIN cfm.pedidos_conformados p ON p.id_origem=h.order_ref
        LEFT JOIN dw.dim_produto pr ON pr.sku=h.product_sku'''))
    cx.execute(text('ALTER TABLE cfm.avaliacoes_conformadas ADD PRIMARY KEY(review_id)'))
    raw_sac=escalar(cx,'SELECT count(*) FROM stg.sac_atendimentos')
    sac_n=escalar(cx,'SELECT count(*) FROM cfm.sac_conformado')
    qa.igual('SAC uma linha por protocolo',sac_n,escalar(cx,'SELECT count(DISTINCT protocolo) FROM stg.sac_atendimentos'))
    qa.igual('avaliacoes cardinalidade preservada',escalar(cx,'SELECT count(*) FROM cfm.avaliacoes_conformadas'),escalar(cx,'SELECT count(*) FROM stg.mkt_avaliacoes'))
    verifica_sql(qa,cx,'SAC encontra pedido e cliente sem multiplicar', 'SELECT count(*) FROM cfm.sac_conformado WHERE cliente_sk IS NULL')
    verifica_sql(qa,cx,'avaliacoes encontram pedido e produto', 'SELECT count(*) FROM cfm.avaliacoes_conformadas WHERE cliente_sk IS NULL OR produto_sk IS NULL')
    verifica_sql(qa,cx,'horas negativas anuladas e sinalizadas','SELECT count(*) FROM cfm.sac_conformado WHERE horas_resolucao<0 OR (tempo_resolucao_invalido AND horas_resolucao IS NOT NULL)')
    verifica_sql(qa,cx,'notas conformadas no dominio','''SELECT (SELECT count(*) FROM cfm.sac_conformado WHERE nota_satisfacao NOT BETWEEN 1 AND 5)
        +(SELECT count(*) FROM cfm.avaliacoes_conformadas WHERE nota NOT BETWEEN 1 AND 5)''')
    verifica_sql(qa,cx,'JSON sem fuso recebe zona assumida', '''SELECT count(*) FROM cfm.avaliacoes_conformadas
        WHERE fuso_assumido AND data_avaliacao_utc AT TIME ZONE 'America/Sao_Paulo' IS DISTINCT FROM raw_horario::timestamp''')
    verifica_sql(qa,cx,'JSON com fuso preserva instante', '''SELECT count(*) FROM cfm.avaliacoes_conformadas
        WHERE NOT fuso_assumido AND data_avaliacao_utc IS DISTINCT FROM raw_horario::timestamptz''')
    m['sac']=dict(brutos=raw_sac,conformados=sac_n,duplicatas_exatas=raw_sac-sac_n,
        cpfs_sem_cadastro=escalar(cx,'''SELECT count(*) FROM stg.sac_atendimentos s WHERE NOT EXISTS(
            SELECT 1 FROM dw.dim_cliente c WHERE c.cpf_normalizado=regexp_replace(s.cpf_cliente,'[^0-9]','','g'))'''),
        cpfs_ausentes=escalar(cx,"SELECT count(*) FROM stg.sac_atendimentos WHERE trim(cpf_cliente)=''"),
        horas_negativas_brutas=escalar(cx,"SELECT count(*) FROM stg.sac_atendimentos WHERE replace(tempo_resolucao_horas,',','.')::numeric<0"),
        horas_anuladas=escalar(cx,'SELECT count(*) FROM cfm.sac_conformado WHERE tempo_resolucao_invalido'),
        notas_invalidas=escalar(cx,'SELECT count(*) FROM cfm.sac_conformado WHERE nota_invalida'),
        sem_fechamento=escalar(cx,'SELECT count(*) FROM cfm.sac_conformado WHERE sem_encerramento_registrado'),
        fechamento_inconsistente=escalar(cx,'SELECT count(*) FROM cfm.sac_conformado WHERE fechamento_inconsistente'))
    m['avaliacoes'] = dict(cx.execute(text('''SELECT count(*) total,count(*) FILTER(WHERE fuso_assumido) sem_fuso,
        count(*) FILTER(WHERE rating_ausente) rating_omitido,count(*) FILTER(WHERE rating_nulo) rating_nulo,
        count(*) FILTER(WHERE tipo_rating_origem='string') rating_string,
        count(*) FILTER(WHERE NOT produto_consta_no_pedido) produto_nao_consta_pedido
        FROM cfm.avaliacoes_conformadas''')).mappings().one())


def inventaria_ausencias(qa, cx, m):
    """Inventário de todas as ausências observadas, sem lhes atribuir causas inventadas."""
    from sqlalchemy import inspect
    from sqlalchemy.types import String
    from sqlalchemy.dialects.postgresql import JSONB
    tabelas=['legado_clientes','legado_produtos','legado_pedidos','legado_itens_pedido',
             'ecom_customer','ecom_category','ecom_product','ecom_orders','ecom_order_item',
             'sac_atendimentos','mkt_avaliacoes']
    inventario=[]
    def regra(t,c):
        if c in ('CPF','tax_id'): return 'nao_coletada; CPF NULL e identidade separada por ID quando ausente'
        if c=='parent_id': return 'nao_aplicavel; identifica raiz da taxonomia'
        if c in ('DT_ENTREGA','delivered_at'): return 'dependente_do_status; nao entregue ou data desconhecida; manter indicador'
        if c=='data_fechamento': return 'encerramento_nao_registrado; nao comprova atendimento em aberto'
        if c in ('nota_satisfacao','rating'): return 'nao_coletada/opcional; manter nota NULL, sem imputacao'
        if c=='verified_purchase': return 'desconhecida; NULL nao equivale a FALSE'
        if c=='helpful_votes': return 'desconhecida; NULL nao equivale a zero votos'
        if c in ('title','comment'): return 'texto_opcional; preservar ausencia, sem inventar conteudo'
        if c in ('CIDADE','city'): return 'nao_coletada/sentinela; NULL na dimensao, original em stg'
        if c=='CATEGORIA': return 'categoria_nao_informada; Outros na dimensao, categoria_origem preservada'
        return 'causa_nao_determinada; preservar NULL e origem, sem imputacao'
    for tabela in tabelas:
        total=escalar(cx,f'SELECT count(*) FROM stg.{tabela}')
        cols=[c for c in inspect(cx).get_columns(tabela,schema='stg') if not c['name'].startswith('_')]
        expressoes=[]
        specs=[]
        for i,c in enumerate(cols):
            campo='"'+c['name']+'"'
            specs.append((c['name'],'chave_omitida' if tabela=='mkt_avaliacoes' else 'NULL_SQL'))
            expressoes.append(f'count(*) FILTER(WHERE {campo} IS NULL) AS v{len(specs)-1}')
            if isinstance(c['type'],String):
                specs.append((c['name'],'vazio_textual'))
                expressoes.append(f"count(*) FILTER(WHERE trim({campo})='') AS v{len(specs)-1}")
                specs.append((c['name'],'sentinela_textual_NULL_NA'))
                expressoes.append(f"count(*) FILTER(WHERE upper(trim({campo})) IN ('NULL','N/A')) AS v{len(specs)-1}")
            if isinstance(c['type'],JSONB):
                specs.append((c['name'],'null_JSON_explicito'))
                expressoes.append(f"count(*) FILTER(WHERE {campo}='null'::jsonb) AS v{len(specs)-1}")
        valores=cx.execute(text('SELECT '+','.join(expressoes)+f' FROM stg.{tabela}')).one()
        for (campo,classe),n in zip(specs,valores):
            if n:
                inventario.append(dict(tabela=tabela,campo=campo,classificacao=classe,
                                       ocorrencias=n,total=total,tratamento=regra(tabela,campo)))
    for tabela,campo,sql in [
        ('legado_pedidos','DT_ENTREGA', '''SELECT count(*) FROM stg.legado_pedidos WHERE "DT_ENTREGA"='1900-01-01 00:00:00'::timestamp'''),
        ('legado_itens_pedido','VL_DESCONTO', 'SELECT count(*) FROM stg.legado_itens_pedido WHERE "VL_DESCONTO"=-1')]:
        inventario.append(dict(tabela=tabela,campo=campo,classificacao='sentinela_numerica_ou_data',
            ocorrencias=escalar(cx,sql),total=escalar(cx,f'SELECT count(*) FROM stg.{tabela}'),
            tratamento=('data_desconhecida; NULL na conformacao com indicador entrega_sentinela' if campo=='DT_ENTREGA'
                        else 'desconto_desconhecido; zero efetivo na reconciliacao, indicador desconto_nao_informado')))
    cx.execute(text('''CREATE TABLE cfm.inventario_ausencias (
        tabela TEXT,campo TEXT,classificacao TEXT,ocorrencias BIGINT,total BIGINT,tratamento TEXT,
        PRIMARY KEY(tabela,campo,classificacao))'''))
    insere(cx,'cfm','inventario_ausencias',inventario)
    verifica_sql(qa,cx,'ausencias sem regra de tratamento', "SELECT count(*) FROM cfm.inventario_ausencias WHERE tratamento IS NULL OR tratamento='' OR ocorrencias>total")
    verifica_sql(qa,cx,'cidade N/A nao e cidade valida', "SELECT count(*) FROM dw.dim_cliente WHERE upper(trim(cidade))='N/A'")
    verifica_sql(qa,cx,'CPF ausente nao foi unificado entre pessoas', '''SELECT count(*) FROM cfm.clientes_origem WHERE cpf_ausente
        AND cliente_sk IN (SELECT cliente_sk FROM cfm.clientes_origem GROUP BY cliente_sk HAVING count(*)>1)''')
    verifica_sql(qa,cx,'nota JSON ausente mantida NULL', 'SELECT count(*) FROM cfm.avaliacoes_conformadas WHERE (rating_ausente OR rating_nulo) AND nota IS NOT NULL')
    m['ausencias']=inventario
