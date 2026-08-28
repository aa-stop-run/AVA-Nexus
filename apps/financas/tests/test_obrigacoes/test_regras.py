from datetime import date
from decimal import Decimal

import pytest

from ava.obrigacoes.regras import (
    calcular_datas_imi,
    calcular_proxima_data_iuc,
    calcular_proxima_inspecao,
    sincronizar_obrigacoes_ativo,
)
from ava.repositories import obrigacao_repo, titular_repo, ativo_repo


def test_calcular_proxima_inspecao_primeira_aos_4_anos():
    matricula = date(2022, 3, 10)
    assert calcular_proxima_inspecao(matricula, referencia=date(2023, 1, 1)) == date(2026, 3, 10)


def test_calcular_proxima_inspecao_avanca_apos_a_primeira():
    matricula = date(2016, 3, 10)
    assert calcular_proxima_inspecao(matricula, referencia=date(2024, 6, 1)) == date(2025, 3, 10)


def test_calcular_proxima_inspecao_lida_com_29_de_fevereiro():
    matricula = date(2020, 2, 29)
    assert calcular_proxima_inspecao(matricula, referencia=date(2025, 1, 1)) == date(2026, 2, 28)


def test_calcular_proxima_data_iuc_no_mesmo_ano():
    matricula = date(2015, 9, 20)
    assert calcular_proxima_data_iuc(matricula, referencia=date(2026, 3, 1)) == date(2026, 9, 20)


def test_calcular_proxima_data_iuc_avanca_para_o_ano_seguinte_se_ja_passou():
    matricula = date(2015, 9, 20)
    assert calcular_proxima_data_iuc(matricula, referencia=date(2026, 10, 1)) == date(2027, 9, 20)


def test_calcular_datas_imi_uma_prestacao():
    assert calcular_datas_imi(2026, valor_total=Decimal("80")) == [date(2026, 5, 31)]


def test_calcular_datas_imi_duas_prestacoes():
    assert calcular_datas_imi(2026, valor_total=Decimal("300")) == [date(2026, 5, 31), date(2026, 11, 30)]


def test_calcular_datas_imi_tres_prestacoes():
    assert calcular_datas_imi(2026, valor_total=Decimal("900")) == [
        date(2026, 5, 31),
        date(2026, 8, 31),
        date(2026, 11, 30),
    ]


@pytest.mark.asyncio
async def test_sincronizar_obrigacoes_ativo_cria_inspecao_e_iuc_sem_duplicar(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    veiculo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    await db_session.commit()

    await sincronizar_obrigacoes_ativo(
        db_session,
        titular_id=titular.id,
        matricula=date(2022, 3, 10),
        referencia=date(2026, 1, 1),
        ativo_id=veiculo.id,
        ativo_nome=veiculo.nome,
    )
    await sincronizar_obrigacoes_ativo(
        db_session,
        titular_id=titular.id,
        matricula=date(2022, 3, 10),
        referencia=date(2026, 1, 1),
        ativo_id=veiculo.id,
        ativo_nome=veiculo.nome,
    )

    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    tipos = sorted(o.tipo for o in pendentes)
    assert tipos == ["inspecao", "iuc"]
    assert all(o.ativo_id == veiculo.id for o in pendentes)
    assert all("Corsa" in o.descricao for o in pendentes)


@pytest.mark.asyncio
async def test_sincronizar_obrigacoes_ativo_dois_veiculos_mesma_matricula_nao_deduplica_entre_si(
    db_session,
):
    # Regressão do Finding 1 (revisão de confirmação, fix batch E): antes de veiculo_id existir
    # na chave de dedupe, dois veiculos do mesmo titular com a MESMA data de matricula produziam
    # datas de obrigação (proxima_inspecao/proxima_iuc) IDÊNTICAS — existe_obrigacao(tipo,
    # data_limite, titular_id) via então a segunda obrigação como "duplicada" da primeira e
    # descartava-a silenciosamente, mesmo pertencendo a um veiculo diferente.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    matricula_partilhada = date(2022, 3, 10)
    veiculo_a = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=matricula_partilhada
    )
    veiculo_b = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Clio", data_aquisicao=matricula_partilhada
    )
    await db_session.commit()

    await sincronizar_obrigacoes_ativo(
        db_session,
        titular_id=titular.id,
        matricula=matricula_partilhada,
        referencia=date(2026, 1, 1),
        ativo_id=veiculo_a.id,
        ativo_nome=veiculo_a.nome,
    )
    await sincronizar_obrigacoes_ativo(
        db_session,
        titular_id=titular.id,
        matricula=matricula_partilhada,
        referencia=date(2026, 1, 1),
        ativo_id=veiculo_b.id,
        ativo_nome=veiculo_b.nome,
    )

    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    # 4 obrigações no total: inspecao + iuc para CADA veiculo, não 2 (o bug original deduplicava
    # a segunda dupla contra a primeira por terem a mesma data_limite/titular_id).
    assert len(pendentes) == 4
    assert sorted(o.tipo for o in pendentes) == ["inspecao", "inspecao", "iuc", "iuc"]

    obrigacoes_por_veiculo = {veiculo_a.id: [], veiculo_b.id: []}
    for obrigacao in pendentes:
        obrigacoes_por_veiculo[obrigacao.ativo_id].append(obrigacao)
    assert sorted(o.tipo for o in obrigacoes_por_veiculo[veiculo_a.id]) == ["inspecao", "iuc"]
    assert sorted(o.tipo for o in obrigacoes_por_veiculo[veiculo_b.id]) == ["inspecao", "iuc"]
    assert all("Corsa" in o.descricao for o in obrigacoes_por_veiculo[veiculo_a.id])
    assert all("Clio" in o.descricao for o in obrigacoes_por_veiculo[veiculo_b.id])
