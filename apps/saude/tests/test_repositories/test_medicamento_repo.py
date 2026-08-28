import pytest
from datetime import datetime, timezone
from saude.repositories.medicamento_repo import MedicamentoRepository


@pytest.mark.asyncio
async def test_crud_medicamento_e_registo_toma(db_session):
    repo = MedicamentoRepository(db_session)
    med = await repo.criar_medicamento(
        titular="aa-stop-run",
        nome="Sertralina",
        principio_ativo="Cloridrato de Sertralina",
        dosagem="50 mg",
        stock_atual=10,
        stock_minimo_alerta=5,
        horarios=[{"hora": "08:30", "quantidade_dose": 1.0, "dias_semana": "todos"}]
    )
    assert med.id is not None
    assert med.stock_atual == 10
    assert len(med.horarios) == 1

    # Registar toma executada
    registo = await repo.registar_toma(
        medicamento_id=med.id,
        data_hora_prevista=datetime.now(timezone.utc),
        registado_via="mobile_notification"
    )
    assert registo.estado == "tomado"

    # Verificar decremento de stock
    med_atualizado = await repo.obter_por_id(med.id)
    assert med_atualizado.stock_atual == 9

    # Repor stock (+30 pills)
    await repo.repor_stock(med.id, quantidade=30)
    med_com_novo_stock = await repo.obter_por_id(med.id)
    assert med_com_novo_stock.stock_atual == 39

    # Obter lista de medicamentos por titular
    lista_alex = await repo.listar_por_titular("aa-stop-run")
    assert len(lista_alex) == 1
    assert lista_alex[0].nome == "Sertralina"

    # Teste de alerta de stock baixo
    await repo.ajustar_stock(med.id, novo_stock=4)
    baixo_stock = await repo.obter_medicamentos_stock_baixo()
    assert len(baixo_stock) == 1
    assert baixo_stock[0]["nome"] == "Sertralina"
    assert baixo_stock[0]["dias_autonomia"] <= 4

    # Teste de schedule sync para os próximos 7 dias
    schedule = await repo.obter_schedule_sync(dias=7)
    assert len(schedule) >= 7
    assert schedule[0]["medicamento_id"] == med.id
    assert schedule[0]["hora"] == "08:30"
