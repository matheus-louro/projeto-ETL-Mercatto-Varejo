"""Fotografia determinística do DW/ABT/auditoria e comparação integral.

Compara chaves, valores, tipos, restrições e sequências. COPY evita carregar
milhões de linhas em memória. QA é opcional: seu histórico cresce a cada teste.
"""
import argparse
import hashlib
import json
from pathlib import Path
from sqlalchemy import inspect, text
from config import eng_dw, DIR_SAIDA
from qualidade.assercoes import Suite
from semana2_utils import salva_json, finaliza


class Digest:
    def __init__(self):
        self.digest=hashlib.sha256()

    def write(self, data):
        if isinstance(data,str):
            data=data.encode('utf-8')
        self.digest.update(data)


def fotografia(cx, incluir_qa=False):
    insp=inspect(cx)
    saida={}
    cx.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    cx.execute(text("SET LOCAL DateStyle='ISO, YMD'"))
    q=cx.dialect.identifier_preparer.quote
    for schema in ['dw','abt','aud']+(['qa'] if incluir_qa else []):
        for nome in sorted(insp.get_table_names(schema=schema)):
            ref=q(schema)+'.'+q(nome)
            cols=insp.get_columns(nome,schema=schema)
            pks=insp.get_pk_constraint(nome,schema=schema)['constrained_columns']
            if not pks:
                raise RuntimeError('Tabela sem chave determinística: '+ref)
            digest=Digest()
            sql=f'COPY (SELECT * FROM {ref} ORDER BY '+','.join(map(q,pks))+') TO STDOUT'
            with cx.connection.driver_connection.cursor() as cur:
                cur.copy_expert(sql,digest)
            constraints=cx.execute(text('''SELECT pg_get_constraintdef(oid)
                FROM pg_constraint WHERE conrelid=CAST(:ref AS regclass) ORDER BY 1'''),{'ref':schema+'.'+nome}).scalars().all()
            saida[schema+'.'+nome]={
                'linhas':cx.execute(text(f'SELECT count(*) FROM {ref}')).scalar_one(),
                'sha256':digest.digest.hexdigest(),
                'colunas':[(c['name'],str(c['type']),c['nullable'],c.get('default')) for c in cols],
                'restricoes':constraints}
            print('Verificado '+schema+'.'+nome,flush=True)
    seqs=cx.execute(text("SELECT schemaname,sequencename,last_value FROM pg_sequences WHERE schemaname IN ('dw','abt','aud') ORDER BY 1,2")).all()
    saida['_sequencias']=[list(r) for r in seqs]
    return saida


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    modo=ap.add_mutually_exclusive_group(required=True)
    modo.add_argument('--gravar-referencia',action='store_true')
    modo.add_argument('--comparar',action='store_true')
    ap.add_argument('--referencia',default='semana3_referencia.json')
    ap.add_argument('--etapa',default='03_verificacao_reexecucao')
    ap.add_argument('--incluir-qa',action='store_true')
    args=ap.parse_args()
    dw=eng_dw()
    with dw.begin() as cx:
        atual=fotografia(cx,args.incluir_qa)
    # Normaliza tuplas para comparar com JSON recarregado.
    atual=json.loads(json.dumps(atual))
    if args.gravar_referencia:
        salva_json(args.referencia,atual)
        return
    ref=json.loads(Path(DIR_SAIDA,args.referencia).read_text(encoding='utf-8'))
    qa=Suite(etapa=args.etapa)
    qa.igual('mesmo conjunto de tabelas',set(atual)==set(ref),True)
    for t in sorted(ref):
        if t=='_sequencias':
            qa.igual('sequencias preservadas',atual.get(t)==ref[t],True)
        else:
            for campo in ['linhas','sha256','colunas','restricoes']:
                qa.igual(campo+' '+t,atual.get(t,{}).get(campo)==ref[t][campo],True)
    salva_json(args.etapa+'_resultado.json',dict(aprovado=not qa.falhou(),tabelas=atual))
    finaliza(qa,dw,args.etapa+'_qa.json')


if __name__=='__main__':
    main()
