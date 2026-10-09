# Execução do diagnóstico — Entrega 1

O script adicional `etl/diagnostico_chaves.py` mede a cobertura de chaves sobre
as fontes completas. Ele executa apenas consultas SELECT nos bancos, lê os
arquivos CSV/NDJSON e grava resultados em `saida/`. Não corrige dados nas
origens e não grava no DW.

Os scripts fornecidos pelo professor, `config.py`, o Dockerfile e o
`requirements.txt` original foram preservados. A dependência complementar
`cryptography` é necessária para a autenticação do PyMySQL com o MySQL 8
encontrada neste ambiente. Ela está declarada separadamente em
`etl/requirements_diagnostico.txt`.

Na pasta `lab-etl-varejo`, após subir o ambiente:

```powershell
docker compose exec -T etl pip install -r requirements_diagnostico.txt
docker compose exec -T etl python 00_perfilamento.py
docker compose exec -T etl python diagnostico_chaves.py
docker compose exec -T etl python diagnostico_semantica.py
```

A instalação complementar deve ser repetida caso o contêiner ETL seja recriado
a partir da imagem original.

A normalização de representações no script adicional serve apenas para medir
correspondências em memória; seus resultados não são persistidos nas fontes.
Os números completos da questão (a) ficam em `saida/diagnostico_chaves.json`.
As medições da questão (b) ficam em `saida/diagnostico_semantica.json`.
