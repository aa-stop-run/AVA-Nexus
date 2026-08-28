from datetime import date
from decimal import Decimal

import pytest

from ava.extraction.validadores import (
    data_plausivel,
    iban_valido,
    nif_valido,
    soma_linhas_igual_total,
    valor_dentro_magnitude_historica,
)


def test_soma_linhas_igual_total_aceita_dentro_da_tolerancia():
    assert soma_linhas_igual_total([Decimal("10.00"), Decimal("35.67")], Decimal("45.67")) is True


def test_soma_linhas_igual_total_rejeita_diferenca_grande():
    assert soma_linhas_igual_total([Decimal("10.00"), Decimal("20.00")], Decimal("45.67")) is False


@pytest.mark.parametrize(
    ("nif", "esperado"),
    [
        ("196694531", True),
        ("196694532", False),
        ("196694540", True),
        ("12345678", False),
        ("12345678a", False),
    ],
)
def test_nif_valido(nif, esperado):
    assert nif_valido(nif) is esperado


@pytest.mark.parametrize(
    ("iban", "esperado"),
    [
        ("PT50000201231234567890154", True),
        ("PT50000201231234567890155", False),
        ("PT50", False),
    ],
)
def test_iban_valido(iban, esperado):
    assert iban_valido(iban) is esperado


def test_data_plausivel_aceita_data_recente():
    assert data_plausivel(date(2026, 7, 20), referencia=date(2026, 7, 27)) is True


def test_data_plausivel_rejeita_data_muito_futura():
    assert data_plausivel(date(2027, 1, 1), referencia=date(2026, 7, 27)) is False


def test_data_plausivel_rejeita_data_muito_antiga():
    assert data_plausivel(date(2020, 1, 1), referencia=date(2026, 7, 27)) is False


def test_valor_dentro_magnitude_historica_sem_historico_aceita_sempre():
    assert valor_dentro_magnitude_historica(Decimal("999.99"), []) is True


def test_valor_dentro_magnitude_historica_rejeita_desvio_grande():
    historico = [Decimal("45.00"), Decimal("48.00"), Decimal("50.00")]
    assert valor_dentro_magnitude_historica(Decimal("500.00"), historico) is False


def test_valor_dentro_magnitude_historica_aceita_variacao_normal():
    historico = [Decimal("45.00"), Decimal("48.00"), Decimal("50.00")]
    assert valor_dentro_magnitude_historica(Decimal("52.00"), historico) is True


def test_valor_dentro_magnitude_historica_media_zero_aceita_sempre():
    historico = [Decimal("-5.00"), Decimal("5.00")]
    assert valor_dentro_magnitude_historica(Decimal("999.00"), historico) is True


def test_valor_dentro_magnitude_historica_verificar_minimo_false_aceita_valor_baixo():
    # Registo rápido (despesa/rendimento avulsos) desliga o piso — variação
    # dia-a-dia para baixo da média é normal, não uma anomalia (ao contrário de faturas).
    historico = [Decimal("20.00"), Decimal("25.00"), Decimal("30.00")]
    assert (
        valor_dentro_magnitude_historica(Decimal("3.00"), historico, verificar_minimo=False) is True
    )


def test_valor_dentro_magnitude_historica_verificar_minimo_false_ainda_rejeita_teto():
    # o teto (ameaça real: LLM leu mal o valor) continua ativo mesmo com o piso desligado.
    historico = [Decimal("20.00"), Decimal("25.00"), Decimal("30.00")]
    assert (
        valor_dentro_magnitude_historica(Decimal("120.00"), historico, verificar_minimo=False)
        is False
    )


def test_valor_dentro_magnitude_historica_verificar_minimo_true_e_o_default():
    # validar_fatura (faturas de fornecedor) não passa verificar_minimo — deve continuar a
    # rejeitar um valor muito abaixo da média, banda simétrica original inalterada.
    historico = [Decimal("45.00"), Decimal("48.00"), Decimal("50.00")]
    assert valor_dentro_magnitude_historica(Decimal("1.00"), historico) is False


def test_iban_valido_rejeita_caracter_invalido_em_base36():
    assert iban_valido("PT50000201231234567890!54") is False
