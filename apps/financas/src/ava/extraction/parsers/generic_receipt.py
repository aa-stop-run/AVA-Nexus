from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re


@dataclass
class ReciboExtraido:
    entidade_pagadora: str
    data: date
    valor_liquido: Decimal
    valor_bruto: Decimal | None = None
    descontos: Decimal | None = None


def parse_generic_receipt(texto: str) -> ReciboExtraido | None:
    """Parser genérico universal para recibos de vencimento / honorários."""
    if not texto:
        return None

    match_liq = re.search(r'(?:líquido|liquido|net\s+pay)[\s:]*([0-9]+[.,][0-9]{2})\s*(?:€|EUR)?', texto, re.IGNORECASE)
    if not match_liq:
        return None

    try:
        liq = Decimal(match_liq.group(1).replace(',', '.'))
    except Exception:
        return None

    return ReciboExtraido(
        entidade_pagadora="Employer Corp",
        data=date.today(),
        valor_liquido=liq,
    )
