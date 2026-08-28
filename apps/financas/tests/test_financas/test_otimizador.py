import pytest
from datetime import date
from decimal import Decimal
from ava.financas.otimizador import (
    SubscricaoDetetada,
    DesvioCategoria,
    calcular_anualizado,
    calcular_desvio_mensal,
    calcular_resumo_poupanca,
)

def test_calcular_anualizado_mensal():
    assert calcular_anualizado(Decimal("14.99"), periodicidade="mensal") == Decimal("179.88")

def test_calcular_anualizado_anual():
    assert calcular_anualizado(Decimal("59.90"), periodicidade="anual") == Decimal("59.90")

def test_calcular_anualizado_trimestral():
    assert calcular_anualizado(Decimal("30.00"), periodicidade="trimestral") == Decimal("120.00")

def test_calcular_desvio_mensal_excesso():
    d = calcular_desvio_mensal(
        categoria_id=None,
        categoria_nome="Restaurantes",
        grupo_nome="Alimentação",
        gasto_mes_atual=Decimal("250.00"),
        media_historica=Decimal("150.00"),
    )
    assert d.diferenca_valor == Decimal("100.00")
    assert d.diferenca_percentagem == Decimal("66.67")
    assert d.tem_excesso is True
    assert d.sugestao_poupanca_10pct == Decimal("25.00")

def test_calcular_desvio_mensal_sem_excesso():
    d = calcular_desvio_mensal(
        categoria_id=None,
        categoria_nome="Supermercado",
        grupo_nome="Alimentação",
        gasto_mes_atual=Decimal("300.00"),
        media_historica=Decimal("310.00"),
    )
    assert d.diferenca_valor == Decimal("-10.00")
    assert d.tem_excesso is False

def test_calcular_resumo_poupanca():
    subscricoes = [
        SubscricaoDetetada(
            id="sub-1",
            nome="Netflix",
            categoria_nome="Streaming",
            valor_periodo=Decimal("15.99"),
            periodicidade="mensal",
            custo_anual=Decimal("191.88"),
            acao_simulada="cancelar",
        ),
        SubscricaoDetetada(
            id="sub-2",
            nome="Spotify",
            categoria_nome="Música",
            valor_periodo=Decimal("10.99"),
            periodicidade="mensal",
            custo_anual=Decimal("131.88"),
            acao_simulada="manter",
        ),
    ]
    desvios = [
        DesvioCategoria(
            categoria_id=None,
            categoria_nome="Restaurantes",
            grupo_nome="Alimentação",
            gasto_mes_atual=Decimal("200.00"),
            media_historica=Decimal("100.00"),
            diferenca_valor=Decimal("100.00"),
            diferenca_percentagem=Decimal("100.00"),
            tem_excesso=True,
            sugestao_poupanca_10pct=Decimal("20.00"),
        )
    ]
    resumo = calcular_resumo_poupanca(subscricoes, desvios)
    # 15.99 mensal de subscrição cancelada + 20.00 sugestão de corte em desvio = 35.99 €/mês
    assert resumo["poupanca_mensal_estimada"] == Decimal("35.99")
    # 191.88 anual de subscrição cancelada + (20.00 * 12 = 240.00) = 431.88 €/ano
    assert resumo["poupanca_anual_estimada"] == Decimal("431.88")
