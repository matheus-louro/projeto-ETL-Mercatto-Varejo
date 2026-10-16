#!/usr/bin/env python3
"""Semana 2: conformação atômica; resultados em cfm e dimensões, sem alterar stg."""
from sqlalchemy import text
from config import eng_dw
from qualidade.assercoes import Suite
from semana2_utils import finaliza, salva_json
from transformacoes_semana2 import (
    prepara, unifica_clientes, conforma_status, conforma_valores,
    conforma_categorias, trata_datas_e_ausencias, liga_sac_e_avaliacoes,
    inventaria_ausencias, FUSO_NEGOCIO)


def main():
    dw=eng_dw()
    qa=Suite(etapa='02_transformacao')
    metricas=dict(versao='0.2.1',fuso_negocio=FUSO_NEGOCIO)
    try:
        with dw.begin() as cx:
            prepara(cx)
            for etapa in [unifica_clientes,conforma_status,conforma_valores,
                          conforma_categorias,trata_datas_e_ausencias,
                          liga_sac_e_avaliacoes,inventaria_ausencias]:
                print(etapa.__name__,flush=True)
                etapa(qa,cx,metricas)
            if qa.falhou():
                raise RuntimeError('Asserções em falha: conformação revertida, consulte qa.execucao_assercao')
    except Exception as exc:
        qa.igual('transformacao sem excecao',0,1,str(exc).splitlines()[0])
        qa.registrar(dw)
        qa.imprimir()
        raise
    metricas['assercoes']=len(qa.resultados)
    qa.igual('transformacao sem excecao',1,1)
    metricas['assercoes']=len(qa.resultados)
    salva_json('semana2_resultados.json',metricas)
    finaliza(qa,dw,'semana2_qa_transformacao.json')


if __name__=='__main__':
    main()
