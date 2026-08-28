import pytest
from datetime import date
from decimal import Decimal
from veiculos.logica.consumos import calcular_medias_abastecimentos, AbastecimentoInput


def test_calcular_consumo_medio_dois_atestos():
    abastecimentos = [
        AbastecimentoInput(
            data=date(2026, 7, 1),
            km=100000,
            quantidade=Decimal("50.00"),
            preco_total=Decimal("80.00"),
            tanque_cheio=True,
        ),
        AbastecimentoInput(
            data=date(2026, 7, 15),
            km=100800,  # 800 km percorridos
            quantidade=Decimal("44.00"),  # 44L para voltar a encher
            preco_total=Decimal("70.40"),
            tanque_cheio=True,
        ),
    ]

    resultado = calcular_medias_abastecimentos(abastecimentos)
    # (44 / 800) * 100 = 5.50 L/100km
    assert resultado["consumo_medio_geral"] == Decimal("5.50")
    assert resultado["total_km_percorridos"] == 800
    assert resultado["total_gasto"] == Decimal("150.40")
    assert resultado["custo_por_km"] == Decimal("0.088")


def test_calcular_consumo_sem_abastecimentos_suficientes():
    abastecimentos = [
        AbastecimentoInput(
            data=date(2026, 7, 1),
            km=100000,
            quantidade=Decimal("50.00"),
            preco_total=Decimal("80.00"),
            tanque_cheio=True,
        ),
    ]
    resultado = calcular_medias_abastecimentos(abastecimentos)
    assert resultado["consumo_medio_geral"] is None
    assert resultado["total_gasto"] == Decimal("80.00")
