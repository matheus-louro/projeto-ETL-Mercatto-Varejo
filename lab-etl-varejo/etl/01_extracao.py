#!/usr/bin/env python3
"""Etapa 1: cópia integral e tipada; arquivos preservados sem limpeza semântica."""
import csv
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, CHAR, Column, Date, DateTime,
                        Integer, MetaData, Numeric, SmallInteger, String,
                        Table, Text, inspect, select, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from config import ARQ_AVALIACOES, ARQ_SAC, eng_dw, eng_mysql, eng_origem
from qualidade.assercoes import Suite
from semana2_utils import LOTE, digest_linha, finaliza, hash_consulta, salva_json


def tipo_destino(tipo):
    # Equivalência de tipos entre SGBDs; sem converter DECIMAL para float.
    if isinstance(tipo, Boolean): return Boolean()
    if isinstance(tipo, BigInteger): return BigInteger()
    if isinstance(tipo, SmallInteger): return SmallInteger()
    if isinstance(tipo, Integer): return Integer()
    if isinstance(tipo, Numeric): return Numeric(tipo.precision, tipo.scale)
    if isinstance(tipo, DateTime): return DateTime(timezone=getattr(tipo, 'timezone', False))
    if isinstance(tipo, Date): return Date()
    if isinstance(tipo, Text): return Text()
    if isinstance(tipo, CHAR): return CHAR(tipo.length)
    if isinstance(tipo, String): return String(tipo.length)
    raise TypeError(f'Tipo de origem sem mapeamento explícito: {tipo}')


def nova_tabela(cx, nome, colunas):
    tabela = Table(nome, MetaData(), *colunas,
                   Column('_fonte', Text, nullable=False),
                   Column('_extraido_em', DateTime(timezone=True), nullable=False),
                   Column('_linha_origem', BigInteger, nullable=False), schema='stg')
    tabela.drop(cx, checkfirst=True)
    tabela.create(cx)
    return tabela


def extrai_relacional(qa, origem, destino, schema, tabela, nome, fonte, momento):
    insp = inspect(origem)
    cols = insp.get_columns(tabela, schema=schema)
    pks = insp.get_pk_constraint(tabela, schema=schema)['constrained_columns']
    quote = origem.dialect.identifier_preparer.quote
    ref = (quote(schema) + '.' if schema else '') + quote(tabela)
    ordenacao = ','.join(quote(k) for k in pks)
    consulta = f'SELECT * FROM {ref} ORDER BY {ordenacao}'
    digest = hashlib.sha256()
    total = 0
    with origem.connect() as src, destino.begin() as dst:
        esperados = src.execute(text(f'SELECT COUNT(*) FROM {ref}')).scalar_one()
        stg = nova_tabela(dst, nome, [Column(c['name'], tipo_destino(c['type']),
                                                nullable=c['nullable']) for c in cols])
        result = src.execution_options(stream_results=True).execute(text(consulta)).mappings()
        while lote := result.fetchmany(LOTE):
            registros = []
            for row in lote:
                registro = dict(row)
                digest_linha(digest, registro)
                total += 1
                registro.update(_fonte=fonte, _extraido_em=momento, _linha_origem=total)
                registros.append(registro)
            dst.execute(stg.insert(), registros)
        obtidos = dst.execute(select(text('count(*)')).select_from(stg)).scalar_one()
        q = destino.dialect.identifier_preparer.quote
        sql = 'SELECT ' + ','.join(q(c['name']) for c in cols) + f' FROM stg.{nome} ORDER BY ' + ','.join(q(k) for k in pks)
        hash_destino = hash_consulta(dst, sql)
    qa.igual(f'linhas {nome}', obtidos, esperados)
    qa.igual(f'conteudo fiel {nome}', int(hash_destino == digest.hexdigest()), 1,
             'SHA-256 dos valores lidos na origem e na staging, em ordem de PK')
    print(f'{nome}: {total} registros, conteúdo preservado', flush=True)
    return total


def extrai_sac(qa, dw, momento):
    digest = hashlib.sha256()
    total = 0
    with open(ARQ_SAC, encoding='latin-1', newline='') as f, dw.begin() as cx:
        leitor = csv.DictReader(f, delimiter=';')
        campos = leitor.fieldnames
        tabela = nova_tabela(cx, 'sac_atendimentos', [Column(k, Text) for k in campos])
        lote = []
        for row in leitor:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('Registro CSV com número incorreto de campos')
            digest_linha(digest, row)
            total += 1
            row.update(_fonte='sac', _extraido_em=momento, _linha_origem=total)
            lote.append(row)
            if len(lote) >= LOTE:
                cx.execute(tabela.insert(), lote)
                lote = []
        if lote: cx.execute(tabela.insert(), lote)
        qtd = cx.execute(text('SELECT count(*) FROM stg.sac_atendimentos')).scalar_one()
        sql = 'SELECT ' + ','.join('"'+k+'"' for k in campos) + ' FROM stg.sac_atendimentos ORDER BY _linha_origem'
        destino_hash = hash_consulta(cx, sql)
    qa.igual('linhas sac_atendimentos', qtd, total)
    qa.igual('conteudo fiel sac_atendimentos', int(destino_hash == digest.hexdigest()), 1,
             'Campos vazios, NULL literal, vírgula decimal e quebras internas preservados')
    return total


def extrai_avaliacoes(qa, dw, momento):
    # Os nomes originais e os objetos aninhados permanecem na staging.
    # JSONB diferencia número/string; JSON.NULL diferencia null explícito de chave omitida.
    campos = ['review_id', 'order', 'product', 'submitted_at', 'rating', 'title',
              'comment', 'verified_purchase', 'helpful_votes']
    digest = hashlib.sha256()
    total = 0
    with open(ARQ_AVALIACOES, encoding='utf-8') as f, dw.begin() as cx:
        tabela = nova_tabela(cx, 'mkt_avaliacoes', [Column(k, JSONB(none_as_null=True)) for k in campos]
                             + [Column('_registro_original', Text, nullable=False)])
        lote = []
        for linha in f:
            raw = linha.rstrip('\r\n')
            obj = json.loads(raw)
            if set(obj) - set(campos):
                raise ValueError('Chave JSON não prevista: registre o tipo antes da ingestão')
            total += 1
            row = {k: (JSON.NULL if obj[k] is None else obj[k]) if k in obj else None for k in campos}
            digest_linha(digest, {'registro': raw})
            row.update(_fonte='mkt', _extraido_em=momento, _linha_origem=total, _registro_original=raw)
            lote.append(row)
            if len(lote) >= LOTE:
                cx.execute(tabela.insert(), lote)
                lote = []
        if lote: cx.execute(tabela.insert(), lote)
        qtd = cx.execute(text('SELECT count(*) FROM stg.mkt_avaliacoes')).scalar_one()
        destino_hash = hash_consulta(cx, 'SELECT _registro_original AS registro FROM stg.mkt_avaliacoes ORDER BY _linha_origem')
    qa.igual('linhas mkt_avaliacoes', qtd, total)
    qa.igual('conteudo fiel mkt_avaliacoes', int(destino_hash == digest.hexdigest()), 1,
             'Documento original preservado; tipos JSON e omissões mantidos')
    return total


def main():
    dw = eng_dw()
    qa = Suite(etapa='01_extracao')
    momento = datetime.now(timezone.utc)
    contagens = {}
    try:
        for origem, schema, fonte, pares in [
            (eng_mysql(), None, 'legado', [('CLIENTES','legado_clientes'), ('PRODUTOS','legado_produtos'),
                                           ('PEDIDOS','legado_pedidos'), ('ITENS_PEDIDO','legado_itens_pedido')]),
            (eng_origem(), 'shop', 'ecom', [('customer','ecom_customer'), ('category','ecom_category'),
                                          ('product','ecom_product'), ('orders','ecom_orders'), ('order_item','ecom_order_item')])]:
            for tabela, nome in pares:
                contagens[nome] = extrai_relacional(qa, origem, dw, schema, tabela, nome, fonte, momento)
        contagens['sac_atendimentos'] = extrai_sac(qa, dw, momento)
        contagens['mkt_avaliacoes'] = extrai_avaliacoes(qa, dw, momento)
        with dw.connect() as cx:
            qa.igual('protocolos SAC preenchidos', cx.execute(text("SELECT count(*) FROM stg.sac_atendimentos WHERE protocolo IS NULL OR protocolo=''" )).scalar_one(), 0)
            qa.igual('review_id unico', cx.execute(text('SELECT count(*)-count(DISTINCT review_id) FROM stg.mkt_avaliacoes')).scalar_one(), 0)
            qa.igual('documento JSON preserva estrutura e tipos', cx.execute(text('''
                SELECT count(*) FROM stg.mkt_avaliacoes
                WHERE NOT (_registro_original::jsonb @> jsonb_strip_nulls(jsonb_build_object(
                    'order', "order", 'product', product, 'rating', rating)))
            ''')).scalar_one(), 0)
            campos_json=['review_id','order','product','submitted_at','rating','title','comment','verified_purchase','helpful_votes']
            divergencias=' OR '.join(f'(_registro_original::jsonb -> \'{k}\') IS DISTINCT FROM "{k}"' for k in campos_json)
            qa.igual('JSON distingue omissao null e tipos',cx.execute(text('SELECT count(*) FROM stg.mkt_avaliacoes WHERE '+divergencias)).scalar_one(),0)
    except Exception as exc:
        qa.igual('extracao sem excecao', 0, 1, str(exc).splitlines()[0])
        qa.registrar(dw)
        qa.imprimir()
        raise
    salva_json('semana2_contagens_extracao.json', contagens)
    qa.igual('extracao sem excecao',1,1)
    finaliza(qa, dw, 'semana2_qa_extracao.json')


if __name__ == '__main__':
    main()
