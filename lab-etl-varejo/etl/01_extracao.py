#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETAPA 1 — EXTRAÇÃO

Objetivo: trazer as quatro fontes para o esquema `stg` do DW, SEM transformar
significado. Renomear, converter tipo e decidir o que é nulo vem depois.

Regra da camada stg (seção 2.3 do referencial):
  · nomes de coluna espelham a origem;
  · nenhum valor é descartado, corrigido ou reinterpretado;
  · acrescente apenas metadados de procedência:
        _fonte           de onde veio
        _extraido_em     quando
        _linha_origem    posição na origem, quando fizer sentido

Decisão obrigatória a registrar no RDT antes de codificar:
  carga completa ou incremental? Justifique com base no que as origens oferecem.
  -> Registrado na Ficha RDT-01: Carga completa (Full Load) por substituição.

    docker compose exec etl python 01_extracao.py
"""

from datetime import datetime, timezone
import json

import pandas as pd
from sqlalchemy import text

from config import (ARQ_AVALIACOES, ARQ_SAC, eng_dw, eng_mysql, eng_origem)
from qualidade.assercoes import Suite

AGORA = datetime.now(timezone.utc)
LOTE = 50_000          # leia em blocos: a base não cabe confortavelmente na RAM


def grava_stg(df, tabela, engine, primeiro_bloco):
    df["_fonte"] = tabela.split("_")[0]
    df["_extraido_em"] = AGORA
    df.to_sql(tabela, engine, schema="stg",
              if_exists="replace" if primeiro_bloco else "append",
              index=False, method="multi", chunksize=5_000)


def extrai_mysql(qa):
    eng, dw = eng_mysql(), eng_dw()
    tabelas = [
        ("CLIENTES", "legado_clientes"),
        ("PRODUTOS", "legado_produtos"),
        ("PEDIDOS", "legado_pedidos"),
        ("ITENS_PEDIDO", "legado_itens_pedido"),
    ]
    for tab_origem, tab_stg in tabelas:
        with eng.connect() as cx:
            esperados = cx.execute(text(f"SELECT COUNT(*) FROM {tab_origem}")).scalar()
            
            primeiro = True
            total_gravado = 0
            conn = cx.execution_options(stream_results=True)
            for chunk in pd.read_sql(text(f"SELECT * FROM {tab_origem}"), conn, chunksize=LOTE):
                grava_stg(chunk, tab_stg, dw, primeiro)
                primeiro = False
                total_gravado += len(chunk)

        qa.igual(f"linhas {tab_stg}", total_gravado, esperados, f"extração completa de {tab_origem}")
        print(f"  [MySQL] {tab_origem} -> stg.{tab_stg}: {total_gravado} linhas gravadas.")


def extrai_postgres(qa):
    eng, dw = eng_origem(), eng_dw()
    tabelas = [
        ("shop.customer", "ecom_customer"),
        ("shop.category", "ecom_category"),
        ("shop.product", "ecom_product"),
        ("shop.orders", "ecom_orders"),
        ("shop.order_item", "ecom_order_item"),
    ]
    for tab_origem, tab_stg in tabelas:
        with eng.connect() as cx:
            esperados = cx.execute(text(f"SELECT COUNT(*) FROM {tab_origem}")).scalar()
            
            primeiro = True
            total_gravado = 0
            conn = cx.execution_options(stream_results=True)
            for chunk in pd.read_sql(text(f"SELECT * FROM {tab_origem}"), conn, chunksize=LOTE):
                grava_stg(chunk, tab_stg, dw, primeiro)
                primeiro = False
                total_gravado += len(chunk)

        qa.igual(f"linhas {tab_stg}", total_gravado, esperados, f"extração completa de {tab_origem}")
        print(f"  [PG Ecom] {tab_origem} -> stg.{tab_stg}: {total_gravado} linhas gravadas.")


def extrai_sac(qa):
    dw = eng_dw()
    primeiro = True
    total_gravado = 0
    for chunk in pd.read_csv(ARQ_SAC, sep=";", encoding="latin1", dtype=str, chunksize=LOTE):
        grava_stg(chunk, "sac_atendimentos", dw, primeiro)
        primeiro = False
        total_gravado += len(chunk)

    qa.igual("linhas sac_atendimentos", total_gravado, 96140, "extração completa de atendimentos_sac.csv")
    print(f"  [SAC CSV] atendimentos_sac.csv -> stg.sac_atendimentos: {total_gravado} linhas gravadas.")


def extrai_avaliacoes(qa):
    dw = eng_dw()
    primeiro = True
    total_gravado = 0
    lote = []

    with open(ARQ_AVALIACOES, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            order = obj.get("order") or {}
            product = obj.get("product") or {}
            
            lote.append({
                "review_id": obj.get("review_id"),
                "order_ref": order.get("ref"),
                "order_channel": order.get("channel"),
                "product_sku": product.get("sku"),
                "submitted_at": obj.get("submitted_at"),
                "rating": str(obj["rating"]) if "rating" in obj and obj["rating"] is not None else None,
                "title": obj.get("title"),
                "comment": obj.get("comment"),
                "verified_purchase": obj.get("verified_purchase"),
                "helpful_votes": obj.get("helpful_votes"),
            })
            
            if len(lote) >= LOTE:
                df = pd.DataFrame(lote)
                grava_stg(df, "mkt_avaliacoes", dw, primeiro)
                primeiro = False
                total_gravado += len(df)
                lote = []

        if lote:
            df = pd.DataFrame(lote)
            grava_stg(df, "mkt_avaliacoes", dw, primeiro)
            primeiro = False
            total_gravado += len(df)

    qa.igual("linhas mkt_avaliacoes", total_gravado, 160000, "extração completa de avaliacoes_marketplace.json")
    print(f"  [JSON] avaliacoes_marketplace.json -> stg.mkt_avaliacoes: {total_gravado} linhas gravadas.")


if __name__ == "__main__":
    qa = Suite(etapa="01_extracao")
    
    print("Iniciando extração para a camada stg...")
    extrai_mysql(qa)
    extrai_postgres(qa)
    extrai_sac(qa)
    extrai_avaliacoes(qa)

    dw = eng_dw()
    with dw.connect() as cx:
        df_sac = pd.read_sql(text("SELECT protocolo FROM stg.sac_atendimentos"), cx)
        qa.sem_nulos("protocolo do SAC", df_sac["protocolo"], "protocolo é identificador obrigatório no SAC")

        df_mkt = pd.read_sql(text("SELECT review_id FROM stg.mkt_avaliacoes"), cx)
        qa.unico("review_id marketplace", df_mkt["review_id"], "review_id deve ser único no marketplace")

    qa.registrar(dw)
    qa.imprimir()
