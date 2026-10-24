"""Execução atômica, auditoria e verificações das etapas da Semana 3."""
from sqlalchemy import text
from qualidade.assercoes import Suite
from semana2_utils import finaliza, verifica_sql


def executar(etapa, engine, func):
    qa = Suite(etapa=etapa)
    try:
        with engine.begin() as cx:
            cx.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            cx.execute(text("SELECT pg_advisory_xact_lock(202603)"))
            func(cx, qa)
            if qa.falhou():
                raise RuntimeError('Asserção reprovada: alterações revertidas.')
    except Exception as exc:
        qa.igual('execucao concluida', False, True, str(exc))
        finaliza(qa, engine, etapa + '_qa.json')
        raise
    finaliza(qa, engine, etapa + '_qa.json')


def verifica_fks(cx, qa, schemas=('dw', 'abt')):
    """Inspeciona as FKs reais (simples no DDL fornecido), inclusive opcionais."""
    rows = cx.execute(text('''SELECT ns.nspname s, cl.relname t, a.attname c,
        pn.nspname ps, pc.relname pt, pa.attname pk, co.convalidated validada
        FROM pg_constraint co
        JOIN pg_class cl ON cl.oid=co.conrelid JOIN pg_namespace ns ON ns.oid=cl.relnamespace
        JOIN pg_class pc ON pc.oid=co.confrelid JOIN pg_namespace pn ON pn.oid=pc.relnamespace
        JOIN pg_attribute a ON a.attrelid=cl.oid AND a.attnum=co.conkey[1]
        JOIN pg_attribute pa ON pa.attrelid=pc.oid AND pa.attnum=co.confkey[1]
        WHERE co.contype='f' AND ns.nspname IN :schemas
        ORDER BY 1,2,3'''), {'schemas': schemas}).mappings().all()
    for r in rows:
        q = cx.dialect.identifier_preparer.quote
        tabela = q(r['s']) + '.' + q(r['t'])
        pai = q(r['ps']) + '.' + q(r['pt'])
        coluna, pk = q(r['c']), q(r['pk'])
        verifica_sql(qa, cx, f"FK {r['s']}.{r['t']}.{r['c']}",
            f'SELECT count(*) FROM {tabela} f LEFT JOIN {pai} p ON f.{coluna}=p.{pk} '
            f'WHERE f.{coluna} IS NOT NULL AND p.{pk} IS NULL')
    qa.igual('FKs validadas no catalogo', sum(not r['validada'] for r in rows), 0)
