"""Verifica reexecução das etapas 1 e 2 contra uma referência obtida da primeira execução."""
import argparse
import json
from pathlib import Path

from sqlalchemy import inspect, text
from config import DIR_SAIDA, eng_dw
from qualidade.assercoes import Suite
from semana2_utils import finaliza, hash_consulta, salva_json


def fotografia(cx):
    insp=inspect(cx)
    saida={}
    for schema in ['stg','cfm','dw']:
        nomes=insp.get_table_names(schema=schema)
        if schema=='dw': nomes=[n for n in nomes if n in ('dim_cliente','dim_produto','dim_status')]
        if schema=='stg': nomes=[n for n in nomes if n.startswith(('legado_','ecom_')) or n in ('sac_atendimentos','mkt_avaliacoes')]
        for nome in sorted(nomes):
            cols=[c['name'] for c in insp.get_columns(nome,schema=schema) if c['name']!='_extraido_em']
            pks=insp.get_pk_constraint(nome,schema=schema)['constrained_columns']
            ordem=pks or (['_linha_origem'] if '_linha_origem' in cols else [cols[0]])
            quote=lambda s: '"'+s.replace('"','""')+'"'
            ref=f'{schema}.{nome}'
            sql='SELECT '+','.join(map(quote,cols))+' FROM '+ref+' ORDER BY '+','.join(map(quote,ordem))
            print('Verificando '+ref,flush=True)
            saida[ref]=dict(linhas=cx.execute(text('SELECT count(*) FROM '+ref)).scalar_one(),
                           sha256=hash_consulta(cx,sql))
    return saida


def main():
    parser=argparse.ArgumentParser()
    modo=parser.add_mutually_exclusive_group(required=True)
    modo.add_argument('--gravar-referencia',action='store_true')
    modo.add_argument('--comparar',action='store_true')
    args=parser.parse_args()
    dw=eng_dw()
    with dw.connect() as cx:
        atual=fotografia(cx)
    if args.gravar_referencia:
        salva_json('semana2_referencia.json',atual)
        return
    referencia=json.loads(Path(DIR_SAIDA,'semana2_referencia.json').read_text(encoding='utf-8'))
    qa=Suite(etapa='02_verificacao_reexecucao')
    qa.igual('mesmas tabelas apos reexecucao',int(set(atual)==set(referencia)),1)
    for tab in sorted(referencia):
        qa.igual('linhas estaveis '+tab,atual.get(tab,{}).get('linhas',-1),referencia[tab]['linhas'])
        qa.igual('conteudo estavel '+tab,int(atual.get(tab,{}).get('sha256')==referencia[tab]['sha256']),1)
    # Comparação integral em ordem de chave; só o timestamp operacional foi excluído.
    salva_json('semana2_verificacao.json',dict(tabelas=atual,assercoes=len(qa.resultados),aprovado=not qa.falhou()))
    finaliza(qa,dw,'semana2_qa_reexecucao.json')


if __name__=='__main__':
    main()
