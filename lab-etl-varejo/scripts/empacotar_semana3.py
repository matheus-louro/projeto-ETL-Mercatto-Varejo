"""Empacotamento do código, dump SQL e resultados de validação da Semana 3.

Executar na máquina host: python lab-etl-varejo/scripts/empacotar_semana3.py
Não inclui dados gerados, volumes, .git, caches ou a entrega anterior em ZIP.
"""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SAIDA=ROOT/'lab-etl-varejo'/'saida'
DESTINO=ROOT/'Entrega3_Mercatto'
ZIP=ROOT/'Entrega3_Mercatto.zip'


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for bloco in iter(lambda:f.read(1024*1024),b''):
            h.update(bloco)
    return h.hexdigest()


def main():
    if DESTINO.exists() or ZIP.exists():
        raise SystemExit('Destino de empacotamento já existente.')
    arquivos_qa=['03_carga_dw_qa.json','04_abt_correta_qa.json',
        '03_testes_semana3_qa.json','03_verificacao_reexecucao_qa.json',
        '03_verificacao_cadeia_qa.json','03_verificacao_dump_qa.json']
    for nome in arquivos_qa:
        resultados=json.loads((SAIDA/nome).read_text(encoding='utf-8'))
        if not resultados or any(not r['aprovado'] for r in resultados):
            raise SystemExit('Validação ausente ou reprovada: '+nome)
    if not (SAIDA/'mercatto_semana3.sql').is_file():
        raise SystemExit('Dump SQL ausente')
    DESTINO.mkdir()
    nomes=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard','--','lab-etl-varejo'],cwd=ROOT).decode('utf-8').split('\0')
    nomes=set(n for n in nomes if n and not n.endswith(('docs/PROFESSOR.md','/.env')))
    nomes.update(['Relatorio_Decisoes_RDT_Semana2.md','Relatorio_Decisoes_RDT_Semana3.md'])
    for nome in sorted(nomes):
        fonte=ROOT/nome
        if not fonte.is_file():
            raise SystemExit('Arquivo do snapshot ausente: '+nome)
        destino=DESTINO/nome
        destino.parent.mkdir(parents=True,exist_ok=True)
        dados=fonte.read_bytes()
        # Arquivos de texto com LF para os entrypoints Linux também funcionarem
        # quando o ZIP foi produzido em um checkout Windows com autocrlf.
        destino.write_bytes(dados.replace(b'\r\n',b'\n'))
    shutil.copyfile(SAIDA/'mercatto_semana3.sql',DESTINO/'mercatto_semana3.sql')
    validacao=DESTINO/'validacao'
    validacao.mkdir()
    extras=['semana3_resultados.json','semana3_abt.json','semana3_reconciliacao.json',
        'semana3_referencia.json','semana3_referencia_dump.json',
        '03_verificacao_reexecucao_resultado.json','03_verificacao_cadeia_resultado.json',
        '03_verificacao_dump_resultado.json']
    for nome in arquivos_qa+extras:
        shutil.copyfile(SAIDA/nome,validacao/nome)
    for nome in ['semana2_qa_extracao.json','semana2_qa_transformacao.json']:
        shutil.copyfile(SAIDA/'integracao_semana3'/nome,validacao/('cadeia_'+nome))
    (DESTINO/'LEIA-ME.txt').write_text('''ETL MERCATTO — CARGA E VERIFICAÇÃO
Mineração de Dados — Engenharia da Computação — IFMT
Equipe: Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi

CONTEÚDO
1. Relatorio_Decisoes_RDT_Semana3.md — fichas 10 a 13, resultados e desenho da ABT.
2. mercatto_semana3.sql — DW carregado, ABT correta, auditoria e histórico de QA.
3. lab-etl-varejo/ — snapshot completo do código, Docker, DDL, gerador e instruções.
4. validacao/ — asserções, contagens e hashes da reexecução, cadeia e restauração.
5. Relatorio_Decisoes_RDT_Semana2.md — contexto das decisões anteriores.

EXECUÇÃO E RESTAURAÇÃO
Procedimentos e comandos: lab-etl-varejo/docs/SEMANA3_EXECUCAO.md.
O dump SQL utiliza PostgreSQL 16 e codificação UTF-8. Contém os schemas dw,
abt, aud e qa, com dados, sequências, índices e restrições. A restauração
é realizada em banco vazio e independe da geração das fontes.
As camadas stg e cfm são reconstruídas pelas etapas 1 e 2 do pipeline.

RESULTADOS (ESCALA 1.0)
410.000 pedidos; 1.371.876 itens; 20.577 itens em quarentena;
95.000 atendimentos; 160.000 avaliações; ABT com 110.195 clientes,
24.056 positivos (21,8304%). Diferença financeira: R$ 0,00 nas duas origens.
Carga: 35 asserções; ABT: 12; testes transacionais: 6;
reexecução: 66; cadeia 1–4 em destino vazio: 66; restauração com QA: 70.
Todas essas verificações foram aprovadas. O histórico QA conserva também
execuções de desenvolvimento. O estado validado corresponde à última
execução de cada etapa, conforme as consultas documentadas.

REPOSITÓRIO
https://github.com/matheus-louro/projeto-ETL-Mercatto-Varejo
Versão do código incluído: Semana 3 — carga do DW e ABT correta.
''',encoding='utf-8-sig')
    arquivos=[arquivo for arquivo in sorted(DESTINO.rglob('*')) if arquivo.is_file()]
    with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for arquivo in arquivos:
            z.write(arquivo,arquivo.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(ZIP) as z:
        erro=z.testzip()
        if erro:
            raise RuntimeError('ZIP corrompido: '+erro)
    print(json.dumps({'arquivo':str(ZIP),'bytes':ZIP.stat().st_size,'sha256':sha256(ZIP),
                      'arquivos':len(arquivos)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
