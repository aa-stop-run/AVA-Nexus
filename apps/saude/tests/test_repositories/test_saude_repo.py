import pytest
from datetime import date, datetime, timezone
from decimal import Decimal

from saude.repositories import saude_repo


@pytest.mark.asyncio
async def test_garantir_titulares_e_perfis(db_session):
    perfis = await saude_repo.garantir_titulares_e_perfis(db_session)
    assert len(perfis) == 3
    nomes = [p.titular.nome for p in perfis]
    assert "aa-stop-run" in nomes
    assert "Member" in nomes
    assert "Junior" in nomes


@pytest.mark.asyncio
async def test_registar_consulta_e_medicamento(db_session):
    perfis = await saude_repo.garantir_titulares_e_perfis(db_session)
    perfil_alex = next(p for p in perfis if p.titular.nome == "aa-stop-run")

    c = await saude_repo.registar_consulta(
        db_session,
        perfil_id=perfil_alex.id,
        data_hora=datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc),
        especialidade="Oftalmologia",
        medico="Dr. Manuel Silva",
        local_clinica="Hospital da Luz Lisboa",
        motivo="Consulta de rotina",
        custo=Decimal("85.00"),
    )

    assert c.id is not None
    assert c.especialidade == "Oftalmologia"

    m = await saude_repo.registar_medicamento(
        db_session,
        perfil_id=perfil_alex.id,
        nome="Gotas Oculares",
        posologia="1 gota ao acordar e ao deitar",
        ativo=True,
    )
    assert m.id is not None
    assert m.nome == "Gotas Oculares"

    perfil_atualizado = await saude_repo.obter_perfil_por_id(db_session, perfil_alex.id)
    assert len(perfil_atualizado.consultas) == 1
    assert len(perfil_atualizado.medicamentos) == 1
