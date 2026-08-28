from decimal import Decimal

from ava.financas.deteccao_outlier import avaliar_outlier


def test_avaliar_outlier_dentro_do_normal_devolve_none():
    historico = [Decimal("50.00"), Decimal("55.00"), Decimal("45.00")]
    # média = 50; 120 está dentro de 3x (150)

    assert avaliar_outlier(Decimal("120.00"), historico, categoria_nome="Saúde") is None


def test_avaliar_outlier_acima_do_teto_devolve_mensagem():
    historico = [Decimal("50.00"), Decimal("50.00"), Decimal("50.00")]
    # média = 50; 200 é 4x -- acima do teto de 3x

    mensagem = avaliar_outlier(Decimal("200.00"), historico, categoria_nome="Saúde")

    assert mensagem == "Isto é 4x o normal para Saúde (50,00 € em média)"


def test_avaliar_outlier_valor_baixo_nao_dispara():
    # verificar_minimo=False: um valor invulgarmente baixo não é assinalado, só o teto conta.
    historico = [Decimal("100.00"), Decimal("100.00"), Decimal("100.00")]

    assert avaliar_outlier(Decimal("5.00"), historico, categoria_nome="Saúde") is None


def test_avaliar_outlier_sem_historico_devolve_none():
    assert avaliar_outlier(Decimal("999.99"), [], categoria_nome="Saúde") is None


def test_avaliar_outlier_media_zero_nao_rebenta():
    # Historico teoricamente possível de valores nulos -- não pode dividir por zero.
    historico = [Decimal("0"), Decimal("0")]

    assert avaliar_outlier(Decimal("50.00"), historico, categoria_nome="Saúde") is None
