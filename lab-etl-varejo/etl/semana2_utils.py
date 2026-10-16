"""Apoio às etapas 1 e 2; não altera config.py nem o framework fornecido."""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from config import DIR_SAIDA

LOTE = 10_000


def serializa(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (value.astimezone(timezone.utc) if value.tzinfo else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def digest_linha(digest, row):
    digest.update(json.dumps(dict(row), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), default=serializa).encode("utf-8"))
    digest.update(b"\n")


def salva_json(arquivo, obj):
    Path(DIR_SAIDA).mkdir(parents=True, exist_ok=True)
    Path(DIR_SAIDA, arquivo).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=serializa), encoding="utf-8")


def escalar(cx, sql):
    return cx.execute(text(sql)).scalar_one()


def verifica_sql(qa, cx, nome, sql):
    """O SQL deve contar violações; zero é o resultado esperado."""
    qa.igual(nome, int(escalar(cx, sql)), 0)


def finaliza(qa, engine, arquivo):
    qa.registrar(engine)
    falhas = qa.imprimir()
    salva_json(arquivo, [vars(r) for r in qa.resultados])
    if falhas:
        raise SystemExit(1)


def hash_consulta(cx, sql):
    digest = hashlib.sha256()
    result = cx.execution_options(stream_results=True).execute(text(sql)).mappings()
    while rows := result.fetchmany(LOTE):
        for row in rows:
            digest_linha(digest, row)
    return digest.hexdigest()
