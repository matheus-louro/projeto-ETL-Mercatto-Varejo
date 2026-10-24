# Execução do diagnóstico — Entrega 1

O script adicional `etl/diagnostico_chaves.py` mede a cobertura de chaves sobre
as fontes completas. Ele executa apenas consultas SELECT nos bancos, lê os
arquivos CSV/NDJSON e grava resultados em `saida/`. Não corrige dados nas
origens e não grava no DW.

O perfilador fornecido, `config.py` e o `requirements.txt` original foram
preservados. Na Semana 2, o Dockerfile passou a instalar a dependência complementar
`cryptography`, necessária para a autenticação do PyMySQL com o MySQL 8
neste ambiente. Ela está declarada separadamente em
`etl/requirements_diagnostico.txt`.

Comandos de construção da imagem e execução na pasta `lab-etl-varejo`:

```powershell
docker compose up -d --build
docker compose exec -T etl python 00_perfilamento.py
docker compose exec -T etl python diagnostico_chaves.py
docker compose exec -T etl python diagnostico_semantica.py
```

A dependência agora faz parte da imagem ETL; não é necessário reinstalá-la
manualmente após recriar o contêiner.

A normalização de representações no script adicional serve apenas para medir
correspondências em memória; seus resultados não são persistidos nas fontes.
Os números completos da questão (a) ficam em `saida/diagnostico_chaves.json`.
As medições da questão (b) ficam em `saida/diagnostico_semantica.json`.
