"""Formatação de dinheiro em português europeu (separador de milhares ".", decimal ",").

Módulo puro, mesma razão de `saldos.py`/`natureza.py`: sem sessão, sem I/O. Nunca passa por
`float` -- dinheiro é sempre `Decimal` do início ao fim, incluindo aqui (achado da revisão final
de 2026-08-20 aos insights: a versão anterior desta função, duplicada dentro de
`financas/insights.py`, arredondava via `float()`, o mesmo que o filtro Jinja `format_pt` de
`api/dashboard.py` já fazia -- inofensivo para exibição, mas incoerente com a regra do projeto
num módulo cujo propósito é ser a camada pura e testável).
"""

from decimal import Decimal


def formatar_valor_pt(valor: Decimal) -> str:
    """'1.234,56' -- sem símbolo de moeda: quem chama decide se e onde o '€' entra na frase."""
    quantizado = valor.quantize(Decimal("0.01"))
    sinal = "-" if quantizado < 0 else ""
    inteiro, _, decimais = f"{abs(quantizado):f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{sinal}{'.'.join(grupos)},{decimais}"
