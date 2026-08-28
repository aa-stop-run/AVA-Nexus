from datetime import date
from decimal import Decimal
from ava.models.meta_poupanca import MetaPoupanca
from ava.financas.metas import calcular_progresso_meta


def test_calcular_progresso_meta_com_data():
    meta = MetaPoupanca(
        nome="Férias",
        valor_alvo=Decimal("1200.00"),
        valor_atual=Decimal("600.00"),
        data_alvo=date(2026, 12, 31),
    )
    prog = calcular_progresso_meta(meta, hoje=date(2026, 8, 25))
    assert prog.percentagem == Decimal("50.0")
    assert prog.valor_restante == Decimal("600.00")
    # De 25 de Agosto a 31 de Dezembro são 4 meses restantes (Agosto/Set/Out/Nov/Dez)
    assert prog.meses_restantes == 4
    assert prog.esforco_mensal == Decimal("150.00")
    assert prog.concluida is False


def test_calcular_progresso_meta_concluida():
    meta = MetaPoupanca(
        nome="Reserva",
        valor_alvo=Decimal("1000.00"),
        valor_atual=Decimal("1000.00"),
    )
    prog = calcular_progresso_meta(meta)
    assert prog.percentagem == Decimal("100.0")
    assert prog.valor_restante == Decimal("0.00")
    assert prog.concluida is True
    assert prog.esforco_mensal is None
