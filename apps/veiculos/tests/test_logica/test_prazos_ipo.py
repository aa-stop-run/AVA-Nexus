import pytest
from datetime import date
from veiculos.logica.prazos_ipo import calcular_proxima_ipo, calcular_mes_iuc, verificar_estado_prazos


def test_calcular_proxima_ipo_carro_novo():
    # Carro matriculado em maio de 2024 -> 1ª IPO é em maio de 2028 (4 anos)
    proxima_ipo = calcular_proxima_ipo(
        ano_matricula=2024,
        mes_matricula=5,
        dia_matricula=15,
        tipo="carro",
        referencia=date(2026, 8, 1),
    )
    assert proxima_ipo == date(2028, 5, 15)


def test_calcular_proxima_ipo_carro_5_anos():
    # Carro matriculado em março de 2020 -> fez aos 4 anos (2024), próxima aos 6 anos (2026)
    proxima_ipo = calcular_proxima_ipo(
        ano_matricula=2020,
        mes_matricula=3,
        dia_matricula=10,
        tipo="carro",
        referencia=date(2026, 1, 1),
    )
    assert proxima_ipo == date(2026, 3, 10)


def test_calcular_proxima_ipo_carro_mais_de_8_anos():
    # Carro de 2012 (Sedan 2.0 TDI) -> inspeção anual
    proxima_ipo = calcular_proxima_ipo(
        ano_matricula=2012,
        mes_matricula=7,
        dia_matricula=20,
        tipo="carro",
        referencia=date(2026, 8, 1),
    )
    # Como já passou julho de 2026, a próxima é julho de 2027
    assert proxima_ipo == date(2027, 7, 20)


def test_calcular_mes_iuc():
    assert calcular_mes_iuc(mes_matricula=5) == "Maio"
    assert calcular_mes_iuc(mes_matricula=11) == "Novembro"


def test_verificar_estado_prazos():
    estado = verificar_estado_prazos(
        data_proxima_ipo=date(2026, 9, 15),
        mes_matricula_iuc=8,
        data_fim_seguro=date(2026, 12, 31),
        hoje=date(2026, 8, 25),
    )
    # IPO em 21 dias -> alerta ativo
    assert estado["ipo_alerta"] is True
    assert estado["ipo_dias_restantes"] == 21
    # IUC é em agosto (mês atual) -> alerta ativo
    assert estado["iuc_mes_atual"] is True
    # Seguro em dezembro -> normal
    assert estado["seguro_alerta"] is False
