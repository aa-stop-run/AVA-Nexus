import pytest
from decimal import Decimal
from hub.services.consolidator import _calcular_radar_proativo


def test_radar_alerta_medicamento_stock_baixo():
    medicamentos_stock_baixo = [
        {
            "id": 1,
            "nome": "Sertralina",
            "dosagem": "50 mg",
            "titular": "aa-stop-run",
            "stock_atual": 4,
            "stock_minimo_alerta": 7,
            "dias_autonomia": 4,
            "urgente": False,
        },
        {
            "id": 2,
            "nome": "Metformina",
            "dosagem": "850 mg",
            "titular": "Member",
            "stock_atual": 2,
            "stock_minimo_alerta": 10,
            "dias_autonomia": 1,
            "urgente": True,
        }
    ]

    radar = _calcular_radar_proativo(
        veiculos=[],
        equipamentos_casa=[],
        consultas_futuras=[],
        obrigacoes_fiscais=[],
        saldo_mes=Decimal("500.00"),
        receitas_mes=Decimal("2000.00"),
        medicamentos_stock_baixo=medicamentos_stock_baixo,
    )

    alertas_farmacia = [item for item in radar if "FARMÁCIA" in item.get("badge", "") or "MEDICAÇÃO" in item.get("badge", "")]
    assert len(alertas_farmacia) == 2
    
    # Metformina deve ser crítico (<= 3 dias)
    met = next(a for a in alertas_farmacia if "Metformina" in a["titulo"])
    assert met["nivel"] == "critico"
    assert "Member" in met["titulo"]

    # Sertralina deve ser aviso
    sert = next(a for a in alertas_farmacia if "Sertralina" in a["titulo"])
    assert sert["nivel"] == "aviso"
    assert "aa-stop-run" in sert["titulo"]
