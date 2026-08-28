"""Deteção de outlier ao categorizar um movimento à mão ("isto é 3x o normal para X").

Estruturalmente diferente do sistema de insights (`ava.financas.insights`): não é para listar,
é uma sugestão contextual no momento de escolher a categoria no ecrã "Movimentos por
categorizar" -- ver spec 2026-08-20-insights-financeiros-design.md §7.1.

Módulo puro, mesma razão de `saldos.py`/`natureza.py`/`insights.py`: sem sessão, sem I/O.
"""

from decimal import Decimal

from ava.extraction.validadores import valor_dentro_magnitude_historica
from ava.financas.formatacao import formatar_valor_pt


def avaliar_outlier(
    valor: Decimal, historico: list[Decimal], *, categoria_nome: str
) -> str | None:
    """Uma frase curta se `valor` for muito acima do histórico desta categoria, ou `None` se
    estiver dentro do normal.

    Reaproveita `valor_dentro_magnitude_historica` -- a mesma lógica que já protege a ingestão
    de faturas (spec §7.1), aqui com `verificar_minimo=False`: um valor invulgarmente BAIXO
    raramente é um erro que valha a pena assinalar (mesma razão documentada em
    `financas.registo_rapido`, que desliga o piso pelo mesmo motivo) -- só o teto é o sinal real.
    """
    if valor_dentro_magnitude_historica(valor, historico, verificar_minimo=False):
        return None
    # Ter chegado aqui já garante `historico` não vazio e média != 0: são exatamente as duas
    # condições que fazem `valor_dentro_magnitude_historica` devolver True (dentro) mais acima --
    # nenhuma delas sobrevive a esta linha.
    media = sum(historico, Decimal("0")) / len(historico)
    multiplo = valor / media
    return f"Isto é {multiplo:.0f}x o normal para {categoria_nome} ({formatar_valor_pt(media)} € em média)"
