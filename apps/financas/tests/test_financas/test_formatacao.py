from decimal import Decimal

from ava.financas.formatacao import formatar_valor_pt


def test_formatar_valor_pt_sem_milhares():
    assert formatar_valor_pt(Decimal("12.99")) == "12,99"


def test_formatar_valor_pt_com_milhares():
    assert formatar_valor_pt(Decimal("1234.56")) == "1.234,56"


def test_formatar_valor_pt_milhoes():
    assert formatar_valor_pt(Decimal("1234567.89")) == "1.234.567,89"


def test_formatar_valor_pt_negativo():
    assert formatar_valor_pt(Decimal("-400.00")) == "-400,00"


def test_formatar_valor_pt_zero():
    assert formatar_valor_pt(Decimal("0")) == "0,00"


def test_formatar_valor_pt_arredonda_para_duas_casas():
    assert formatar_valor_pt(Decimal("3.005")) == "3,00"
