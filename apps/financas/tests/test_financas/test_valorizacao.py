from datetime import date
from decimal import Decimal

import pytest

from ava.financas.valorizacao import TAXAS_POR_TIPO, projetar, taxa_de


def test_taxa_do_ativo_ganha_a_omissao_do_tipo():
    assert taxa_de("carro", Decimal("-0.30")) == Decimal("-0.30")


def test_sem_taxa_propria_usa_a_omissao_do_tipo():
    assert taxa_de("carro", None) == TAXAS_POR_TIPO["carro"]
    assert taxa_de("casa", None) == TAXAS_POR_TIPO["casa"]


def test_tipo_desconhecido_nao_inventa_taxa():
    # Nunca adivinha uma taxa para uma categoria que não conhece — 0 é a única opção honesta.
    assert taxa_de("barco", None) == Decimal("0")


def test_taxa_zero_e_respeitada_e_nao_confundida_com_none():
    # Decimal("0") é falsy: um `taxa_anual or TAXAS_POR_TIPO[...]` trocaria uma taxa
    # explicitamente 0 pela omissão do tipo.
    assert taxa_de("carro", Decimal("0")) == Decimal("0")


def test_projetar_na_propria_data_devolve_o_valor_observado():
    valor = projetar(Decimal("10000.00"), date(2026, 1, 1), date(2026, 1, 1), Decimal("-0.15"))
    assert valor == Decimal("10000.00")


def test_projetar_um_ano_aplica_a_taxa_uma_vez():
    # 2025 tem 365 dias; 365/365.25 = 0.99932..., por isso o resultado fica muito perto de
    # 8500 mas não exatamente. Arredonda-se a cêntimos e compara-se com tolerância de 1 €.
    valor = projetar(Decimal("10000.00"), date(2025, 1, 1), date(2026, 1, 1), Decimal("-0.15"))
    assert Decimal("8499") <= valor <= Decimal("8501")


def test_projetar_valoriza_quando_a_taxa_e_positiva():
    valor = projetar(Decimal("200000.00"), date(2025, 1, 1), date(2026, 1, 1), Decimal("0.02"))
    assert Decimal("203900") <= valor <= Decimal("204100")


def test_projetar_com_taxa_zero_mantem_o_valor():
    valor = projetar(Decimal("5000.00"), date(2020, 1, 1), date(2026, 1, 1), Decimal("0"))
    assert valor == Decimal("5000.00")


def test_projetar_devolve_decimal_com_dois_casas():
    valor = projetar(Decimal("10000.00"), date(2025, 1, 1), date(2026, 7, 3), Decimal("-0.15"))
    assert isinstance(valor, Decimal)
    assert valor.as_tuple().exponent == -2


def test_projetar_nunca_desce_abaixo_de_zero():
    # Uma taxa composta é assintótica: por muitos anos que passem, não chega a negativo.
    valor = projetar(Decimal("10000.00"), date(1990, 1, 1), date(2026, 1, 1), Decimal("-0.15"))
    assert valor > Decimal("0")


def test_projetar_para_data_anterior_a_observacao_e_erro_de_programacao():
    # Quem chama tem de escolher a observação certa primeiro (obter_valor_em_data).
    with pytest.raises(ValueError):
        projetar(Decimal("10000.00"), date(2026, 1, 1), date(2025, 1, 1), Decimal("-0.15"))


def test_taxa_menor_ou_igual_a_menos_um_levanta_erro_em_vez_de_devolver_lixo():
    # Base não positiva não tem potência real. Antes, via float, isto devolvia silenciosamente
    # um número complexo; agora dá InvalidOperation, que é o que um valor sem sentido merece.
    from decimal import InvalidOperation

    with pytest.raises(InvalidOperation):
        projetar(Decimal("10000.00"), date(2025, 1, 1), date(2026, 1, 1), Decimal("-1.5"))
