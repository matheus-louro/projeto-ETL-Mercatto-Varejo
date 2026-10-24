"""Testes transacionais: futuro não altera atributos; cliente ausente bloqueia carga.
As mutações são sempre revertidas. Somente as asserções ficam persistidas.
"""
import importlib
from sqlalchemy import text
from config import DATA_CORTE, eng_dw
from qualidade.assercoes import Suite
from semana2_utils import escalar, finaliza, hash_consulta


def main():
    abt=importlib.import_module('04_abt')
    carga=importlib.import_module('03_carga_dw')
    dw=eng_dw()
    qa=Suite(etapa='03_testes_semana3')
    with dw.connect() as cx:
        tx=cx.begin()
        try:
            cx.execute(text('SELECT pg_advisory_xact_lock(202603)'))
            cols='cliente_sk,'+','.join(abt.COLUNAS)
            sql=f'SELECT {cols} FROM ({abt.consulta()}) x ORDER BY cliente_sk'
            antes=hash_consulta(cx,sql)
            cx.execution_options(stream_results=False)
            n=cx.execute(text(f"UPDATE dw.fato_pedido SET valor_total=0 WHERE data_pedido_sk>DATE '{DATA_CORTE}'")).rowcount
            qa.maior_igual('teste altera pedidos futuros',n,1)
            n=cx.execute(text(f"UPDATE dw.fato_avaliacao SET nota=1 WHERE data_sk>DATE '{DATA_CORTE}'")).rowcount
            qa.maior_igual('teste altera avaliacoes futuras',n,1)
            n=cx.execute(text(f"UPDATE dw.fato_atendimento SET horas_resolucao=999,nota_satisfacao=1 WHERE data_abertura_sk>DATE '{DATA_CORTE}'")).rowcount
            qa.maior_igual('teste altera atendimentos futuros',n,1)
            # Retira também a associação a clientes, impedindo contagens futuras ocultas.
            cx.execute(text(f"UPDATE dw.fato_atendimento SET pedido_sk=NULL,cliente_sk=NULL WHERE data_abertura_sk>DATE '{DATA_CORTE}'"))
            cx.execute(text(f"UPDATE dw.fato_avaliacao SET pedido_sk=NULL WHERE data_sk>DATE '{DATA_CORTE}'"))
            depois=hash_consulta(cx,sql)
            cx.execution_options(stream_results=False)
            qa.igual('atributos invariantes a alteracoes no futuro',antes==depois,True)
        finally:
            tx.rollback()
        tx=cx.begin()
        try:
            fatos=escalar(cx,'SELECT count(*) FROM dw.fato_pedido')
            cx.execute(text('UPDATE cfm.pedidos_conformados SET cliente_sk=NULL WHERE id_origem=(SELECT min(id_origem) FROM cfm.pedidos_conformados)'))
            ensaio=Suite(etapa='ensaio_nao_persistido')
            bloqueou=False
            try:
                carga.dimensoes(cx,ensaio)
            except RuntimeError as exc:
                bloqueou='RDT-12' in str(exc)
            qa.igual('pedido sem cliente bloqueia publicacao',bloqueou,True)
            qa.igual('bloqueio preserva os fatos existentes',escalar(cx,'SELECT count(*) FROM dw.fato_pedido'),fatos)
        finally:
            tx.rollback()
    finaliza(qa,dw,'03_testes_semana3_qa.json')


if __name__=='__main__':
    main()
