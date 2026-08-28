from datetime import date

import pytest

from ava.repositories.obrigacao_repo import criar_obrigacao, existe_obrigacao, listar_pendentes
from ava.repositories import titular_repo, ativo_repo


@pytest.mark.asyncio
async def test_listar_pendentes_ordena_por_data_limite(db_session):
    await criar_obrigacao(
        db_session, tipo="iuc", descricao="IUC do carro", data_limite=date(2026, 9, 1), origem="regra"
    )
    await criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção periódica",
        data_limite=date(2026, 8, 1),
        origem="regra",
    )

    pendentes = await listar_pendentes(db_session)

    assert [o.tipo for o in pendentes] == ["inspecao", "iuc"]


@pytest.mark.asyncio
async def test_existe_obrigacao_dedupe_e_por_veiculo_nao_apenas_tipo_data_titular(db_session):
    # Finding 1 (revisão de confirmação, fix batch E): a chave de dedupe original
    # (tipo, data_limite, titular_id) confundia obrigações de veiculos DIFERENTES do mesmo
    # titular com a mesma data_limite calculada — veiculo_id é o quarto campo que as distingue.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    veiculo_a = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    veiculo_b = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Clio", data_aquisicao=date(2022, 3, 10)
    )
    await db_session.commit()

    data_limite = date(2026, 3, 10)
    await criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção periódica obrigatória — Corsa",
        data_limite=data_limite,
        origem="regra",
        titular_id=titular.id,
        ativo_id=veiculo_a.id,
    )
    await db_session.commit()

    # mesmo tipo/data/titular, mas veiculo diferente -> NÃO é considerado duplicado.
    assert (
        await existe_obrigacao(
            db_session,
            tipo="inspecao",
            data_limite=data_limite,
            titular_id=titular.id,
            ativo_id=veiculo_b.id,
        )
        is False
    )

    # mesmo veiculo -> É considerado duplicado.
    assert (
        await existe_obrigacao(
            db_session,
            tipo="inspecao",
            data_limite=data_limite,
            titular_id=titular.id,
            ativo_id=veiculo_a.id,
        )
        is True
    )
