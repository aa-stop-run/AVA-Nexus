from decimal import Decimal
import pytest
from ava.financas.simulador_credito import calcular_amortizacao, ResultadoSimulacao


def test_calculo_prestacao_e_amortizacao_reduzir_prestacao():
    # Exemplo: Capital 150.000€, Taxa 3.5%, Prazo 25 anos (300 meses), Amortizar 5.000€ com 0.5% comissão
    res = calcular_amortizacao(
        capital_atual=Decimal("150000.00"),
        taxa_anual=Decimal("3.5"),
        prazo_meses=300,
        valor_amortizar=Decimal("5000.00"),
        taxa_comissao=Decimal("0.5"),
    )
    # Prestação atual: ~750.90€
    assert abs(res.prestacao_atual - Decimal("750.90")) < Decimal("0.10")
    # Cenário 1: Reduzir prestação (mantém 300 meses)
    # Nova prestação: ~725.87€
    assert abs(res.cenario_reduzir_prestacao.nova_prestacao - Decimal("725.87")) < Decimal("0.10")
    assert abs(res.cenario_reduzir_prestacao.poupanca_mensal - Decimal("25.03")) < Decimal("0.10")
    assert res.cenario_reduzir_prestacao.novo_prazo_meses == 300
    assert res.comissao_bancaria == Decimal("25.00")
    assert res.cenario_reduzir_prestacao.poupanca_total_juros > Decimal("2000.00")


def test_calculo_amortizacao_reduzir_prazo():
    res = calcular_amortizacao(
        capital_atual=Decimal("150000.00"),
        taxa_anual=Decimal("3.5"),
        prazo_meses=300,
        valor_amortizar=Decimal("5000.00"),
        taxa_comissao=Decimal("0.5"),
    )
    # Cenário 2: Reduzir prazo (mantém prestação ~750.90€)
    # Novo prazo deve ser menor que 300 meses (poupa ~14-16 meses)
    assert res.cenario_reduzir_prazo.novo_prazo_meses < 300
    assert res.cenario_reduzir_prazo.meses_poupados > 0
    assert res.cenario_reduzir_prazo.nova_prestacao == res.prestacao_atual
    # Poupança de juros ao reduzir prazo é substancialmente maior que ao reduzir prestação
    assert res.cenario_reduzir_prazo.poupanca_total_juros > res.cenario_reduzir_prestacao.poupanca_total_juros


def test_comissao_zero():
    res = calcular_amortizacao(
        capital_atual=Decimal("100000.00"),
        taxa_anual=Decimal("3.0"),
        prazo_meses=240,
        valor_amortizar=Decimal("2000.00"),
        taxa_comissao=Decimal("0.0"),
    )
    assert res.comissao_bancaria == Decimal("0.00")


def test_validacao_capital_e_amortizacao():
    with pytest.raises(ValueError, match="Capital em dívida tem de ser positivo"):
        calcular_amortizacao(
            capital_atual=Decimal("-100"),
            taxa_anual=Decimal("3"),
            prazo_meses=120,
            valor_amortizar=Decimal("500"),
        )

    with pytest.raises(
        ValueError, match="Valor a amortizar não pode ser superior ao capital em dívida"
    ):
        calcular_amortizacao(
            capital_atual=Decimal("5000"),
            taxa_anual=Decimal("3"),
            prazo_meses=120,
            valor_amortizar=Decimal("6000"),
        )
