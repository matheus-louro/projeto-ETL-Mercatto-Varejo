"""Empacotamento da entrega final (Semana 4): código, dumps, relatórios, fluxos Orange e validações.

Executar na máquina host: python lab-etl-varejo/scripts/empacotar_semana4.py
"""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAIDA = ROOT / 'lab-etl-varejo' / 'saida'
DESTINO = ROOT / 'EntregaFinal_Mercatto'
ZIP = ROOT / 'EntregaFinal_Mercatto.zip'

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b''):
            h.update(bloco)
    return h.hexdigest()

def main():
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    if ZIP.exists():
        ZIP.unlink()
        
    # Verificar relatórios obrigatórios
    relatorios = [
        'Relatorio_Decisoes_RDT_Final.pdf',
        'Relatorio_Decisoes_RDT_Final.md',
        'Relatorio_Experimento_Vazamento.pdf',
        'Relatorio_Experimento_Vazamento.md',
        'GUIA_DEFESA_ORAL_SEMANA4.md'
    ]
    for r in relatorios:
        if not (ROOT / r).is_file():
            raise SystemExit(f'Relatório obrigatório ausente: {r}')
            
    DESTINO.mkdir(parents=True)
    
    # Copiar Relatórios para a raiz da entrega
    for r in relatorios:
        shutil.copyfile(ROOT / r, DESTINO / r)
        
    # Copiar Pasta de Fluxos do Orange e Gráficos
    fluxos_dest = DESTINO / 'fluxos_orange'
    fluxos_dest.mkdir(parents=True)
    for ows in (ROOT / 'fluxos_orange').glob('*.ows'):
        shutil.copyfile(ows, fluxos_dest / ows.name)
        
    graficos_dest = DESTINO / 'graficos_experimento'
    graficos_dest.mkdir(parents=True)
    for img in (ROOT / 'relatorios_semana4' / 'imagens').glob('*.png'):
        shutil.copyfile(img, graficos_dest / img.name)
        
    # Copiar código do repositório
    nomes = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'lab-etl-varejo'],
        cwd=ROOT
    ).decode('utf-8').split('\0')
    nomes = set(n for n in nomes if n and not n.endswith(('docs/PROFESSOR.md', '/.env', '.pyc')) and not 'saida/mercatto_' in n)
    for nome in sorted(nomes):
        fonte = ROOT / nome
        if fonte.is_file():
            dest = DESTINO / nome
            dest.parent.mkdir(parents=True, exist_ok=True)
            dados = fonte.read_bytes()
            dest.write_bytes(dados.replace(b'\r\n', b'\n'))
            
    # Copiar Validações
    validacao_dest = DESTINO / 'validacao'
    if (ROOT / 'validacao').exists():
        shutil.copytree(ROOT / 'validacao', validacao_dest, dirs_exist_ok=True)
        
    # Criar LEIA-ME da Entrega Final
    (DESTINO / 'LEIA-ME.txt').write_text("""ETL MERCATTO VAREJO — ENTREGA FINAL (SEMANA 4)
Mineração de Dados — Engenharia da Computação — IFMT 2026/2
Equipe: Matheus Henrique Moreira Louro e Lucas Ribeiro Luchesi
Prof. Orlando Júnior

CONTEÚDO DA ENTREGA:
1. Relatorio_Decisoes_RDT_Final.pdf (e .md)
   - Registro de Decisões de Transformação integral (Fichas RDT-01 a RDT-17).
   - Tabela-Resumo consolidando todas as transformações, populações e perdas.
   - Reflexão final (máx. 400 palavras) sobre sensibilidade e impacto em pessoas reais.

2. Relatorio_Experimento_Vazamento.pdf (e .md)
   - Relatório rigorosamente formatado em 4 páginas.
   - Resposta fundamentada às três perguntas obrigatórias:
     (a) Comparativo completo de AUC e Acurácia Balanceada (Naive Bayes, Regressão Logística, Árvore).
     (b) Mensuração isolada do impacto do vazamento sutil (normalização Z-score global).
     (c) Protocolo de auditoria às cegas para detecção de vazamento temporal e metodológico.

3. fluxos_orange/
   - fluxo_recompra_correta.ows (workflow do Orange para a versão limpa).
   - fluxo_recompra_vazamento.ows (workflow do Orange para a versão com vazamento).

4. graficos_experimento/
   - Painéis de Curvas ROC, Comparativo de Barras, Histograma de Recência Negativa e Importância de Atributos.

5. GUIA_DEFESA_ORAL_SEMANA4.md
   - Roteiro estruturado para a defesa oral de 15 minutos com respostas às armadilhas da banca.

6. lab-etl-varejo/
   - Pipeline de ETL completo e reexecutável do zero (Etapas 00 a 05).

7. validacao/
   - Asserções de QA, contagens e metadados das quatro semanas de desenvolvimento.

COMANDOS PARA REEXECUÇÃO DO PIPELINE DO ZERO:
  docker compose down -v && rm -rf dados saida
  docker compose up -d --build
  docker compose exec etl python 01_extracao.py
  docker compose exec etl python 02_transformacao.py
  docker compose exec etl python 03_carga_dw.py
  docker compose exec etl python 04_abt.py --correta
  docker compose exec etl python 04_abt.py --vazamento
  docker compose exec etl python 05_exportar_orange.py
""", encoding='utf-8-sig')

    # Gerar o ZIP da Entrega Final
    print("Gerando arquivo ZIP da entrega final...")
    with zipfile.ZipFile(ZIP, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(DESTINO.rglob('*')):
            if f.is_file():
                z.write(f, f.relative_to(ROOT).as_posix())
                
    print(f"Entrega final empacotada com sucesso em: {ZIP} ({ZIP.stat().st_size / (1024*1024):.2f} MB)")

if __name__ == '__main__':
    main()
