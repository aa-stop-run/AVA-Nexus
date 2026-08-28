from datetime import date
from decimal import Decimal, InvalidOperation

import pytest

from ava.financas.saldos import (JANELA_CASAMENTO_DIAS, RECONCILIACAO_DESDE,
                                 TIPOS_PASSIVO, derivar, parse_valor_pt, sinal_de)


def test_sinal_das_contas_de_ativo():
    for tipo in ("a_ordem", "poupanca", "cartao_refeicao", "investimento"):
        assert sinal_de(tipo) == 1


def test_sinal_das_contas_de_passivo():
    for tipo in ("divida", "emprestimo", "cartao_credito"):
        assert sinal_de(tipo) == -1


def test_tipo_desconhecido_conta_como_ativo():
    # Um tipo novo que ninguem previu e mais provavelmente uma conta do que uma divida, e um
    # falso positivo de "ativo" e visivel no /patrimonio; um falso "passivo" subtraia em
    # silencio.
    assert sinal_de("cripto") == 1


def test_derivar_numa_conta_de_ativo():
    # 1000 + 200 entradas - 50 saidas
    assert derivar(
        Decimal("1000.00"), Decimal("200.00"), Decimal("50.00"), tipo="a_ordem"
    ) == Decimal("1150.00")


def test_derivar_numa_conta_de_passivo():
    # Uma divida de 1000 com 300 de amortizacao a entrar fica em 700: dinheiro que entra
    # numa divida reduz o que se deve.
    assert derivar(
        Decimal("1000.00"), Decimal("300.00"), Decimal("0.00"), tipo="emprestimo"
    ) == Decimal("700.00")


def test_derivar_num_cartao_de_credito_ao_gastar():
    # Gastar num cartao aumenta a divida: 100 devidos + 40 de gasto = 140.
    assert derivar(
        Decimal("100.00"), Decimal("0.00"), Decimal("40.00"), tipo="cartao_credito"
    ) == Decimal("140.00")


def test_derivar_sem_movimentos_devolve_a_ancora():
    assert derivar(
        Decimal("42.17"), Decimal("0"), Decimal("0"), tipo="a_ordem"
    ) == Decimal("42.17")


def test_derivar_e_sempre_decimal():
    resultado = derivar(Decimal("10"), Decimal("3"), Decimal("1"), tipo="a_ordem")
    assert isinstance(resultado, Decimal)


def test_constantes():
    assert JANELA_CASAMENTO_DIAS == 7
    assert RECONCILIACAO_DESDE == date(2026, 8, 8)
    assert set(TIPOS_PASSIVO) == {"divida", "emprestimo", "cartao_credito"}


def test_parse_valor_pt_com_separador_de_milhares():
    # REGRESSAO (revisao final, achado 2): "4.281,55" e o formato que format_pt ja mostra em
    # toda a app -- o primeiro numero que o utilizador tenciona escrever, o saldo real da conta
    # a ordem, tem quatro digitos. Sem tirar o ponto de milhares primeiro, Decimal via
    # InvalidOperation em ".55" apos a troca ingenua de "," por ".".
    assert parse_valor_pt("4.281,55") == Decimal("4281.55")


def test_parse_valor_pt_sem_separador_de_milhares():
    assert parse_valor_pt("556,80") == Decimal("556.80")


def test_parse_valor_pt_sem_virgula_mantem_o_ponto_como_decimal():
    # Sem virgula nenhuma, um ponto e o proprio separador decimal (ex. escrito a americana) --
    # nao ha ambiguidade a resolver, por isso fica intocado.
    assert parse_valor_pt("9.99") == Decimal("9.99")


def test_parse_valor_pt_texto_nao_numerico_levanta_invalid_operation():
    with pytest.raises(InvalidOperation):
        parse_valor_pt("abc")


def test_parse_valor_pt_recusa_formato_americano():
    # REGRESSAO (re-revisao, achado 1): "1,234.56" tem virgula, por isso entrava no ramo que tira
    # pontos de milhares -- "1,234.56" -> "1,23456" -> "1.23456" -> Decimal("1.23456"), que
    # Numeric(12, 2) arredondava para 1,23 em silencio (~1000x menor que o valor real). Um ponto
    # DEPOIS da virgula e formato americano, nao portugues, e nao ha como adivinhar a intencao de
    # quem escreveu -- recusa-se como qualquer outro texto invalido.
    with pytest.raises(InvalidOperation):
        parse_valor_pt("1,234.56")


def test_parse_valor_pt_casos_validos_continuam_a_funcionar():
    # Confirma que a recusa do formato americano nao apanha os casos portugueses legitimos.
    assert parse_valor_pt("4.281,55") == Decimal("4281.55")
    assert parse_valor_pt("1234.56") == Decimal("1234.56")
    assert parse_valor_pt("0,50") == Decimal("0.50")
    assert parse_valor_pt("1234") == Decimal("1234")
    assert parse_valor_pt("1.234.567,89") == Decimal("1234567.89")
