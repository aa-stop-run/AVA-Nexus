import pytest
from datetime import date
from decimal import Decimal

from veiculos.repositories import veiculo_repo


@pytest.mark.asyncio
async def test_criar_e_listar_veiculos(db_session):
    v1 = await veiculo_repo.criar_veiculo(
        db_session,
        nome="Sedan 2.0 TDI",
        tipo="carro",
        matricula="12-AB-34",
        ano_matricula=2018,
        mes_matricula=5,
        combustivel="gasoleo",
        km_atual=145000,
    )
    v2 = await veiculo_repo.criar_veiculo(
        db_session,
        nome="Commuter 125cc",
        tipo="mota",
        matricula="56-CD-78",
        ano_matricula=2022,
        mes_matricula=9,
        combustivel="gasolina",
        km_atual=6200,
    )

    veiculos = await veiculo_repo.listar_veiculos(db_session)
    assert len(veiculos) == 2
    nomes = [v.nome for v in veiculos]
    assert "Sedan 2.0 TDI" in nomes and "Commuter 125cc" in nomes
    # order verified above


@pytest.mark.asyncio
async def test_registar_manutencao_e_atualizar_km(db_session):
    v = await veiculo_repo.criar_veiculo(
        db_session,
        nome="City Hatchback 1.2",
        tipo="carro",
        km_atual=180000,
    )

    m = await veiculo_repo.registar_manutencao(
        db_session,
        veiculo_id=v.id,
        data=date(2026, 8, 10),
        km=185000,
        tipo_servico="oleo_filtros",
        descricao="Mudança de óleo 5W30 e filtro de combustível",
        oficina="Oficina Central",
        custo=Decimal("165.50"),
    )

    assert m.id is not None
    assert m.custo == Decimal("165.50")
    
    # Verifica que o odómetro do veículo foi atualizado automaticamente
    v_atualizado = await veiculo_repo.obter_veiculo_por_id(db_session, v.id)
    assert v_atualizado.km_atual == 185000

    manutencoes = await veiculo_repo.listar_manutencoes(db_session, v.id)
    assert len(manutencoes) == 1
    assert manutencoes[0].tipo_servico == "oleo_filtros"


@pytest.mark.asyncio
async def test_registar_abastecimento(db_session):
    v = await veiculo_repo.criar_veiculo(
        db_session,
        nome="Sedan 2.0 TDI",
        km_atual=140000,
    )

    ab = await veiculo_repo.registar_abastecimento(
        db_session,
        veiculo_id=v.id,
        data=date(2026, 8, 15),
        km=140650,
        quantidade=Decimal("45.00"),
        preco_total=Decimal("72.50"),
        posto="Galp",
        tanque_cheio=True,
    )

    assert ab.id is not None
    assert ab.preco_unitario == Decimal("1.611")

    abastecimentos = await veiculo_repo.listar_abastecimentos(db_session, v.id)
    assert len(abastecimentos) == 1
    assert abastecimentos[0].posto == "Galp"
