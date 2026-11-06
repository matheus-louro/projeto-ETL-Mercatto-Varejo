#!/usr/bin/env python3
"""Compila o Markdown canônico do RDT final em HTML e PDF.

O Markdown é a fonte editável das decisões. A compilação valida as 17 fichas
antes de renderizar, sem reconstruir ou sobrescrever seu conteúdo.
Renderizadores: WeasyPrint ou Chromium em modo headless.
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MD=ROOT/'Relatorio_Decisoes_RDT_Final.md'
HTML=ROOT/'relatorios_semana4/rdt_final.html'
CSS=ROOT/'relatorios_semana4/estilo_rdt.css'
PDF=ROOT/'Relatorio_Decisoes_RDT_Final.pdf'
TMP=ROOT/'tmp/pdfs/rdt_final'


def validar(texto):
    fichas=list(re.finditer(r'^## RDT-(\d{2})[^\n]*',texto,re.MULTILINE))
    if [m.group(1) for m in fichas]!=[f'{i:02d}' for i in range(1,18)]:
        raise ValueError('O RDT deve conter as fichas 01 a 17, sem repetição e em ordem.')
    secoes=[r'\*\*(?:Evidência|O que o dado mostrava)',r'\*\*Alternativas',
            r'\*\*Decisão e justificativa',r'\*\*O que se perde',
            r'\*\*Registros afetados',r'\*\*Asserç']
    for i,m in enumerate(fichas):
        fim=fichas[i+1].start() if i+1<len(fichas) else texto.index('## Tabela-resumo')
        bloco=texto[m.end():fim]
        for secao in secoes:
            if not re.search(secao,bloco):
                raise ValueError(f'Ficha RDT-{m.group(1)} incompleta: {secao}')
    reflexao=texto.split('## Reflexão final',1)
    if len(reflexao)!=2 or len(reflexao[1].split())>400:
        raise ValueError('Reflexão final ausente ou com mais de 400 palavras.')
    if len(re.findall(r'^### [123]\.',reflexao[1],re.MULTILINE))!=3:
        raise ValueError('A reflexão deve responder às três questões do modelo RDT.')


def chromium():
    candidatos=[shutil.which(n) for n in ('chromium','chromium-browser','google-chrome','msedge','chrome')]
    for base in (Path(os.environ.get('PROGRAMFILES','C:/Program Files')),
                 Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))):
        candidatos.extend([base/'Google/Chrome/Application/chrome.exe',
                           base/'Microsoft/Edge/Application/msedge.exe'])
    for p in candidatos:
        if p and Path(p).is_file():
            return str(p)
    return None


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine',choices=['auto','weasyprint','chromium'],default='auto')
    ap.add_argument('--html-only',action='store_true')
    args=ap.parse_args()
    texto=MD.read_text(encoding='utf-8-sig')
    validar(texto)
    pandoc=shutil.which('pandoc')
    if not pandoc:
        raise RuntimeError('Pandoc não encontrado no PATH.')
    HTML.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([pandoc,str(MD),'-o',str(HTML),'--standalone','--mathml',
        '--metadata','title=Registro de Decisões de Transformação - Mercatto',
        '--metadata','lang=pt-BR','--css',CSS.name],check=True)
    if args.html_only:
        print(f'HTML gerado: {HTML}')
        return
    TMP.mkdir(parents=True,exist_ok=True)
    temporario=TMP/PDF.name
    tem_weasyprint=importlib.util.find_spec('weasyprint') is not None
    if args.engine=='weasyprint' or (args.engine=='auto' and tem_weasyprint):
        subprocess.run([sys.executable,'-m','weasyprint',str(HTML),str(temporario)],check=True)
    else:
        navegador=chromium()
        if not navegador:
            raise RuntimeError('WeasyPrint ou Chromium são necessários para renderizar o PDF.')
        subprocess.run([navegador,'--headless','--disable-gpu','--no-pdf-header-footer',
            '--allow-file-access-from-files',f'--user-data-dir={TMP/"perfil_chromium"}',
            f'--print-to-pdf={temporario}',HTML.resolve().as_uri()],
            check=True,capture_output=True,timeout=120)
    if not temporario.is_file() or not temporario.read_bytes().startswith(b'%PDF-'):
        raise RuntimeError('A renderização não produziu um PDF válido.')
    temporario.replace(PDF)
    print(f'RDT validado: 17 fichas e reflexão de até 400 palavras.\nPDF gerado: {PDF}')


if __name__=='__main__':
    main()
