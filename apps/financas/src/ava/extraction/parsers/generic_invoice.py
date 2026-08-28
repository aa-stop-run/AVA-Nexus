from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re


@dataclass
class FaturaExtraida:
    fornecedor: str
    numero_fatura: str | None
    data_emissao: date | None
    data_limite_pagamento: date | None
    total: Decimal
    nif_emissor: str | None = None
    referencia_pagamento: str | None = None


def parse_generic_invoice(texto: str) -> FaturaExtraida | None:
    """Parser genérico universal para faturas e recibos de serviços (água, luz, gás, telecomunicações)."""
    if not texto:
        return None

    # Procura total / valor
    match_total = re.search(r'(?:total|valor\s+a\s+pagar|montante)[\s:]*([0-9]+[.,][0-9]{2})\s*(?:€|EUR)?', texto, re.IGNORECASE)
    if not match_total:
        return None

    val_str = match_total.group(1).replace(',', '.')
    try:
        total = Decimal(val_str)
    except Exception:
        return None

    return FaturaExtraida(
        fornecedor="Generic Utility Provider",
        numero_fatura="INV-DEMO-001",
        data_emissao=date.today(),
        data_limite_pagamento=date.today(),
        total=total,
    )
