"""Medições da questão (a), somente leitura das quatro fontes, sem carga no DW."""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from config import eng_mysql, eng_origem, ARQ_SAC, ARQ_AVALIACOES, DIR_SAIDA


def digits(v):
    return re.sub(r"\D", "", str(v)) if pd.notna(v) else ""


def name(v):
    if pd.isna(v):
        return ""
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(v))
                           if not unicodedata.combining(c)).upper().split())


def email(v):
    return str(v).strip().lower() if pd.notna(v) else ""


def cpf_valid(v):
    if len(v) != 11 or len(set(v)) == 1:
        return False
    for n in (9, 10):
        d = (sum(int(v[i]) * (n + 1 - i) for i in range(n)) * 10) % 11
        if int(v[n]) != (0 if d == 10 else d):
            return False
    return True


def measure(label, values, targets):
    values = list(values)
    targets = set(targets) - {"", None}
    n = len(values)
    filled = sum(v not in ("", None) for v in values)
    hit = sum(v in targets for v in values)
    return dict(candidato=label, total=n, preenchidos=filled,
                ligados=hit, sem_ligacao=n-hit,
                percentual=round(100*hit/n, 4) if n else 0)


def read(engine, sql):
    with engine.connect() as cx:
        return pd.read_sql(text(sql), cx)


leg = read(eng_mysql(), "SELECT ID_CLIENTE,NOME,CPF,EMAIL,TELEFONE FROM CLIENTES")
eco = read(eng_origem(), "SELECT customer_id,full_name,tax_id,email,phone FROM shop.customer")
lp = read(eng_mysql(), "SELECT ID_PEDIDO,ID_CLIENTE FROM PEDIDOS")
ep = read(eng_origem(), "SELECT order_id,customer_id FROM shop.orders")
lprod = read(eng_mysql(), "SELECT ID_PRODUTO FROM PRODUTOS")
eprod = read(eng_origem(), "SELECT product_id,sku FROM shop.product")
li = read(eng_mysql(), "SELECT ID_PEDIDO,ID_PRODUTO FROM ITENS_PEDIDO")
ei = read(eng_origem(), "SELECT order_id,product_id FROM shop.order_item")
out = dict(escala=1.0, clientes={}, cobertura=[], observacoes={})

for label, lc, ec, fn in [("CPF", "CPF", "tax_id", digits),
                         ("E-mail", "EMAIL", "email", email),
                         ("Nome", "NOME", "full_name", name),
                         ("Telefone", "TELEFONE", "phone", digits)]:
    a, b = leg[lc].map(fn), eco[ec].map(fn)
    ca, cb = Counter(v for v in a if v), Counter(v for v in b if v)
    common = set(ca) & set(cb)
    out["clientes"][label] = dict(
        legado_total=len(a), ecommerce_total=len(b),
        legado_preenchidos=sum(ca.values()), ecommerce_preenchidos=sum(cb.values()),
        legado_distintos=len(ca), ecommerce_distintos=len(cb),
        chaves_comuns=len(common),
        legado_ligados=sum(ca[k] for k in common), ecommerce_ligados=sum(cb[k] for k in common),
        legado_chaves_repetidas=sum(v > 1 for v in ca.values()),
        ecommerce_chaves_repetidas=sum(v > 1 for v in cb.values()),
        pares_join=sum(ca[k]*cb[k] for k in common),
        chaves_comuns_unicas_em_ambos=sum(ca[k] == cb[k] == 1 for k in common))
    out["cobertura"].extend([measure(label+" legado -> e-commerce", a, b),
                             measure(label+" e-commerce -> legado", b, a)])
    if label == "CPF":
        out["observacoes"]["cpf"] = dict(
            comuns_validos=sum(cpf_valid(k) for k in common),
            comuns_invalidos=sum(not cpf_valid(k) for k in common),
            legado_invalidos=sum(v for k,v in ca.items() if not cpf_valid(k)),
            ecommerce_invalidos=sum(v for k,v in cb.items() if not cpf_valid(k)))
        leg_cpf, eco_cpf = a, b

orders = {"LEGADO": set(lp.ID_PEDIDO), "ECOM": set(ep.order_id)}
all_orders = {f"LEG-{k}" for k in orders["LEGADO"]} | {f"ECOM-{k}" for k in orders["ECOM"]}
sac = pd.read_csv(ARQ_SAC, sep=";", encoding="latin-1", dtype=str, keep_default_na=False)
sac_keys = [(s, int(i) if i.isdigit() else None) for s,i in zip(sac.origem_sistema, sac.id_pedido_origem)]
target_keys = {(s,k) for s,vals in orders.items() for k in vals}
out["cobertura"].append(measure("SAC (origem_sistema,id_pedido_origem) -> pedidos", sac_keys, target_keys))
for system in orders:
    vals = [k for k in sac_keys if k[0] == system]
    out["cobertura"].append(measure("SAC pedidos "+system, vals, target_keys))
sac_cpf = sac.cpf_cliente.map(digits)
out["cobertura"].append(measure("SAC CPF -> união dos cadastros", sac_cpf, set(leg_cpf) | set(eco_cpf)))
for system, cpfs in [("LEGADO", leg_cpf), ("ECOM", eco_cpf)]:
    vals = sac_cpf[sac.origem_sistema == system]
    out["cobertura"].append(measure("SAC CPF -> cadastro "+system, vals, cpfs))

refs, skus = [], []
with open(ARQ_AVALIACOES, encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        refs.append(obj.get("order", {}).get("ref", ""))
        skus.append(obj.get("product", {}).get("sku", ""))
product_refs = set(eprod.sku) | {f"LEG-{k}" for k in lprod.ID_PRODUTO}
out["cobertura"].append(measure("JSON order.ref -> pedidos com prefixo", refs, all_orders))
out["cobertura"].append(measure("JSON product.sku -> produtos com prefixo", skus, product_refs))
for prefix in ("LEG", "ECOM"):
    out["cobertura"].append(measure("JSON pedidos "+prefix, [v for v in refs if v.startswith(prefix+"-")], all_orders))
for prefix in ("LEG", "SKU"):
    out["cobertura"].append(measure("JSON produtos "+prefix, [v for v in skus if v.startswith(prefix+"-")], product_refs))

for label, vals, targets in [
    ("Legado pedidos -> clientes", lp.ID_CLIENTE, leg.ID_CLIENTE),
    ("E-commerce pedidos -> clientes", ep.customer_id, eco.customer_id),
    ("Legado itens -> pedidos", li.ID_PEDIDO, lp.ID_PEDIDO),
    ("E-commerce itens -> pedidos", ei.order_id, ep.order_id),
    ("Legado itens -> produtos", li.ID_PRODUTO, lprod.ID_PRODUTO),
    ("E-commerce itens -> produtos", ei.product_id, eprod.product_id)]:
    out["cobertura"].append(measure(label, vals, targets))

path = Path(DIR_SAIDA) / "diagnostico_chaves.json"
path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
