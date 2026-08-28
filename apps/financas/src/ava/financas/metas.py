from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from ava.models.meta_poupanca import MetaPoupanca


@dataclass(frozen=True)
class MetaProgresso:
    meta: MetaPoupanca
    percentagem: Decimal
    valor_restante: Decimal
    meses_restantes: int | None
    esforco_mensal: Decimal | None
    concluida: bool


def _arredondar(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_progresso_meta(
    meta: MetaPoupanca, hoje: date | None = None
) -> MetaProgresso:
    if hoje is None:
        hoje = date.today()

    alvo = meta.valor_alvo or Decimal("0.00")
    atual = meta.valor_atual or Decimal("0.00")

    if alvo <= Decimal("0.00"):
        pct = Decimal("100.0") if atual > 0 else Decimal("0.0")
        restante = Decimal("0.00")
        concluida = True
    else:
        pct = _arredondar((atual / alvo) * Decimal("100.0"))
        if pct > Decimal("100.0"):
            pct = Decimal("100.0")
        restante = max(Decimal("0.00"), alvo - atual)
        concluida = atual >= alvo

    meses_restantes = None
    esforco_mensal = None

    if meta.data_alvo and not concluida:
        if meta.data_alvo >= hoje:
            meses = (meta.data_alvo.year - hoje.year) * 12 + (
                meta.data_alvo.month - hoje.month
            )
            if meses <= 0:
                meses = 1
            meses_restantes = meses
            if meses_restantes > 0 and restante > 0:
                esforco_mensal = _arredondar(restante / Decimal(str(meses_restantes)))
        else:
            meses_restantes = 0
            esforco_mensal = restante

    return MetaProgresso(
        meta=meta,
        percentagem=pct,
        valor_restante=restante,
        meses_restantes=meses_restantes,
        esforco_mensal=esforco_mensal,
        concluida=concluida,
    )
