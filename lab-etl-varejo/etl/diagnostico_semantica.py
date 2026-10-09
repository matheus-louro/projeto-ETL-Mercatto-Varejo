"""Questão (b): medições de status, categorias e significado dos totais. SELECT apenas."""
import json
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from config import eng_mysql, eng_origem, DIR_SAIDA

def query(engine, sql):
    with engine.connect() as cx:
        return [dict(row) for row in cx.execute(text(sql)).mappings()]

leg, eco = eng_mysql(), eng_origem()
out = {
    "status_legado": query(leg, "SELECT STATUS status, COUNT(*) n FROM PEDIDOS GROUP BY STATUS ORDER BY n DESC"),
    "status_ecommerce": query(eco, "SELECT status, COUNT(*) n FROM shop.orders GROUP BY status ORDER BY n DESC"),
    "categorias_legado": query(leg, "SELECT MIN(CATEGORIA) categoria, COUNT(*) n FROM PRODUTOS GROUP BY BINARY CATEGORIA ORDER BY n DESC"),
    "categorias_ecommerce": query(eco, "SELECT c.category_id,c.name,c.parent_id,p.name pai,COUNT(pr.product_id) produtos FROM shop.category c LEFT JOIN shop.category p ON p.category_id=c.parent_id LEFT JOIN shop.product pr ON pr.category_id=c.category_id GROUP BY c.category_id,c.name,c.parent_id,p.name ORDER BY c.category_id"),
}
out["valores_legado"] = query(leg, """
SELECT COUNT(*) pedidos,
 SUM(p.VALOR_TOTAL) total_pedidos,
 SUM(i.liquido) total_itens_liquidos,
 SUM(ABS(p.VALOR_TOTAL-i.liquido)<=0.02) bate_sem_frete,
 SUM(ABS(p.VALOR_TOTAL-i.liquido-p.VALOR_FRETE)<=0.02) bate_com_frete,
 SUM(ABS(p.VALOR_TOTAL-i.liquido_bruto-p.VALOR_FRETE)<=0.02) bate_desconto_literal,
 SUM(i.sentinelas>0) pedidos_desconto_sentinela,
 SUM(i.sentinelas) itens_desconto_sentinela,
 SUM(p.VALOR_TOTAL-i.liquido) diferenca_total_itens,
 SUM(p.VALOR_FRETE) frete_total,
 MAX(ABS(p.VALOR_TOTAL-i.liquido-p.VALOR_FRETE)) maior_residuo
FROM PEDIDOS p JOIN (
 SELECT ID_PEDIDO,SUM(QTD*VL_UNITARIO-GREATEST(VL_DESCONTO,0)) liquido,
 SUM(QTD*VL_UNITARIO-VL_DESCONTO) liquido_bruto,
 SUM(VL_DESCONTO=-1) sentinelas FROM ITENS_PEDIDO GROUP BY ID_PEDIDO
) i ON i.ID_PEDIDO=p.ID_PEDIDO
""")
out["valores_ecommerce"] = query(eco, """
SELECT COUNT(*) pedidos,
 SUM(p.total_amount) total_pedidos,
 SUM(i.liquido) total_itens_liquidos,
 COUNT(*) FILTER(WHERE ABS(p.total_amount-i.liquido)<=0.02) bate_sem_frete,
 COUNT(*) FILTER(WHERE ABS(p.total_amount-i.liquido-p.freight_amount)<=0.02) bate_com_frete,
 SUM(p.total_amount-i.liquido) diferenca_total_itens,
 SUM(p.freight_amount) frete_total,
 MAX(ABS(p.total_amount-i.liquido)) maior_residuo
FROM shop.orders p JOIN (
 SELECT order_id,SUM(quantity*unit_price-discount) liquido
 FROM shop.order_item GROUP BY order_id
) i ON i.order_id=p.order_id
""")
def serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)
encoded = json.dumps(out, ensure_ascii=False, indent=2, default=serialize)
Path(DIR_SAIDA, "diagnostico_semantica.json").write_text(encoded, encoding="utf-8")
print(encoded)
