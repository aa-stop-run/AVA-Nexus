from datetime import date
from decimal import Decimal
import pytest
from unittest.mock import AsyncMock, MagicMock

from ava.financas.tesouraria import (
    data_do_mes,
    calcular_projecao_tesouraria,
    EventoTesouraria,
    PontoProjecao,
    ProjecaoTesouraria,
)


def test_data_do_mes():
    assert data_do_mes(2026, 2, 31) == date(2026, 2, 28)
    assert data_do_mes(2026, 4, 31) == date(2026, 4, 30)
    assert data_do_mes(2026, 5, 15) == date(2026, 5, 15)


@pytest.mark.asyncio
async def test_calcular_projecao_tesouraria_mock():
    # Simular sessão com queries de saldo, recorrentes, contratos e veiculos
    session = AsyncMock()

    # Mocks para as 5 queries executadas em sequência
    res_saldo = MagicMock()
    res_saldo.scalar.return_value = Decimal("2500.00")

    res_rec = MagicMock()
    # Salário dia 25 e Crédito habitação dia 1
    mapping_rec = [
        {"tipo": "entrada", "valor": Decimal("2000.00"), "dia_do_mes": 25, "descricao": "Vencimento aa-stop-run", "categoria_nome": "Salário"},
        {"tipo": "saida", "valor": Decimal("750.00"), "dia_do_mes": 1, "descricao": "Prestação BPI", "categoria_nome": "Crédito"},
    ]
    res_rec.mappings.return_value.all.return_value = mapping_rec

    res_contratos = MagicMock()
    mapping_con = [
        {"nome": "EDP Comercial", "tipo": "Energia", "valor": Decimal("120.00"), "data_inicio": date(2026, 1, 7), "data_fim": None, "periodicidade": "mensal"},
        {"nome": "Garantia: Membersung Galaxy Watch 8", "tipo": "garantia", "valor": Decimal("204.90"), "data_inicio": date(2026, 8, 19), "data_fim": date(2029, 8, 19), "periodicidade": "unica"},
    ]
    res_contratos.mappings.return_value.all.return_value = mapping_con

    res_veiculos = MagicMock()
    mapping_vei = [
        {"nome": "Sedan 2.0 TDI", "matricula": "AA-01-BB", "mes_matricula": 11, "ano_matricula": 2018, "tipo": "carro"}
    ]
    res_veiculos.mappings.return_value.all.return_value = mapping_vei

    res_media = MagicMock()
    res_media.scalar.return_value = Decimal("2250.00")  # 25€ / dia

    session.execute.side_effect = [res_saldo, res_rec, res_contratos, res_veiculos, res_media]

    proj = await calcular_projecao_tesouraria(
        session,
        dias_projecao=90,
        margem_seguranca=Decimal("500.00"),
        hoje=date(2026, 9, 1),
    )

    assert proj.saldo_atual == Decimal("2500.00")
    assert len(proj.pontos_diarios) == 90
    assert proj.ponto_minimo_valor > Decimal("-10000.00")
    assert any("Prestação BPI" in e.descricao for e in proj.grandes_compromissos)
    assert any("Vencimento aa-stop-run" in e.descricao for e in proj.grandes_compromissos)
    # Warranties de compras passadas NUNCA devem ser projetadas como despesas futuras
    assert not any("Membersung Galaxy Watch" in e.descricao for e in proj.grandes_compromissos)
