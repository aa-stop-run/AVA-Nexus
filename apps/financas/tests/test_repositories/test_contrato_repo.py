from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import ativo_repo, contrato_repo, titular_repo


@pytest.mark.asyncio
async def test_criar_e_listar_contratos(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="João", tipo="proprio")
    carro = await ativo_repo.criar_ativo(
        db_session,
        titular_id=titular.id,
        tipo="carro",
        nome="BMW 320d",
        data_aquisicao=date(2023, 1, 1),
    )
    await db_session.commit()

    contrato = await contrato_repo.criar_contrato(
        db_session,
        titular_id=titular.id,
        ativo_id=carro.id,
        nome="Seguro Automóvel Tranquilidade",
        tipo="seguro_auto",
        data_inicio=date(2025, 1, 1),
        data_fim=date(2026, 1, 1),
        valor=Decimal("350.00"),
        periodicidade="anual",
    )
    await db_session.commit()

    assert contrato.id is not None
    assert contrato.nome == "Seguro Automóvel Tranquilidade"

    # Listar por ativo
    contratos_do_carro = await contrato_repo.listar_por_ativo(db_session, carro.id)
    assert len(contratos_do_carro) == 1
    assert contratos_do_carro[0].id == contrato.id


@pytest.mark.asyncio
async def test_calculo_encargo_anual_e_vencimentos(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Maria", tipo="proprio")

    # Contrato mensal 30€ (360€/ano)
    await contrato_repo.criar_contrato(
        db_session,
        titular_id=titular.id,
        nome="MEO Fibra",
        tipo="telecomunicacoes",
        data_inicio=date(2025, 5, 1),
        data_fim=date(2026, 9, 1),
        dias_aviso_previo=30,
        valor=Decimal("30.00"),
        periodicidade="mensal",
    )

    # Seguro anual 200€
    await contrato_repo.criar_contrato(
        db_session,
        titular_id=titular.id,
        nome="Seguro Saúde Médis",
        tipo="seguro_saude",
        data_inicio=date(2025, 6, 1),
        data_fim=date(2026, 9, 15),
        dias_aviso_previo=30,
        valor=Decimal("200.00"),
        periodicidade="anual",
    )

    # Garantia (tipo garantia não deve contar para o encargo anual)
    await contrato_repo.criar_contrato(
        db_session,
        titular_id=titular.id,
        nome="Garantia TV Membersung",
        tipo="garantia",
        data_inicio=date(2024, 1, 1),
        data_fim=date(2027, 1, 1),
        valor=Decimal("0.00"),
        periodicidade="unica",
    )
    await db_session.commit()

    total_encargo = await contrato_repo.calcular_encargo_anual_total(db_session)
    assert total_encargo == Decimal("560.00")  # (30 * 12) + 200 = 560

    # Vencimentos nos próximos 60 dias a partir de 2026-08-01
    vencimentos = await contrato_repo.listar_proximos_vencimentos(
        db_session, referencia=date(2026, 8, 1), dias_antecedencia=60
    )
    assert len(vencimentos) == 2
    nomes = [v["contrato"].nome for v in vencimentos]
    assert "MEO Fibra" in nomes
    assert "Seguro Saúde Médis" in nomes


@pytest.mark.asyncio
async def test_desativar_contrato(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    contrato = await contrato_repo.criar_contrato(
        db_session,
        titular_id=titular.id,
        nome="Contrato Antigo",
        tipo="outro",
        data_inicio=date(2024, 1, 1),
    )
    await db_session.commit()

    assert await contrato_repo.desativar_contrato(db_session, contrato.id) is True
    ativos = await contrato_repo.listar_todos(db_session, apenas_ativos=True)
    assert len(ativos) == 0
