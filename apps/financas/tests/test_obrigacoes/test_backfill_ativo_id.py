from datetime import date

import pytest

from ava.obrigacoes.backfill_ativo_id import backfill_ativo_id_obrigacoes_regra
from ava.obrigacoes.regras import (
    calcular_proxima_data_iuc,
    calcular_proxima_inspecao,
    sincronizar_obrigacoes_ativo,
)
from ava.repositories import obrigacao_repo, titular_repo, ativo_repo


async def _rodar_backfill(db_session) -> int:
    # backfill_ativo_id_obrigacoes_regra espera uma Connection SÍNCRONA (é o que
    # op.get_bind() devolve dentro de uma migração Alembic — ver migrations/env.py). Usar
    # AsyncConnection.run_sync reproduz exatamente essa ponte, sem precisar de correr o
    # Alembic dentro do teste.
    conn = await db_session.connection()
    return await conn.run_sync(backfill_ativo_id_obrigacoes_regra)


@pytest.mark.asyncio
async def test_backfill_preenche_ativo_id_quando_titular_tem_um_unico_veiculo(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    veiculo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    # simula uma Obrigacao criada ANTES da migração b2a9258c1b44 (veiculo_id ainda não existia)
    obrigacao = await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção periódica obrigatória",
        data_limite=date(2026, 3, 10),
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await db_session.commit()

    atualizadas = await _rodar_backfill(db_session)
    await db_session.commit()

    assert atualizadas == 1
    await db_session.refresh(obrigacao)
    assert obrigacao.ativo_id == veiculo.id


@pytest.mark.asyncio
async def test_backfill_nao_adivinha_quando_titular_tem_varios_veiculos(db_session):
    # Caso ambíguo: o titular tem DOIS veículos, logo não há forma de saber, a partir dos
    # dados existentes, a qual deles esta obrigação pré-existente pertence. O princípio
    # "nunca adivinhar entre candidatos ambíguos" (já usado noutras partes deste codebase)
    # aplica-se aqui — a linha deve ficar com ativo_id=NULL, não uma escolha arbitrária.
    titular = await titular_repo.criar_titular(db_session, nome="Bruno", tipo="proprio")
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Clio", data_aquisicao=date(2022, 3, 10)
    )
    obrigacao = await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="iuc",
        descricao="Pagamento do IUC",
        data_limite=date(2026, 3, 10),
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await db_session.commit()

    atualizadas = await _rodar_backfill(db_session)
    await db_session.commit()

    assert atualizadas == 0
    await db_session.refresh(obrigacao)
    assert obrigacao.ativo_id is None


@pytest.mark.asyncio
async def test_backfill_ignora_titular_sem_veiculo(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Carla", tipo="proprio")
    obrigacao = await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="iuc",
        descricao="Pagamento do IUC",
        data_limite=date(2026, 3, 10),
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await db_session.commit()

    atualizadas = await _rodar_backfill(db_session)
    await db_session.commit()

    assert atualizadas == 0
    await db_session.refresh(obrigacao)
    assert obrigacao.ativo_id is None


@pytest.mark.asyncio
async def test_backfill_ignora_obrigacoes_fora_do_escopo(db_session):
    # origem != "regra" e tipo fora de (inspecao, iuc) não devem ser tocados pelo backfill,
    # mesmo com ativo_id=NULL e titular com um único veiculo.
    titular = await titular_repo.criar_titular(db_session, nome="Duarte", tipo="proprio")
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    obrigacao_extracao = await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção (extraída de documento)",
        data_limite=date(2026, 3, 10),
        origem="extracao",
        titular_id=titular.id,
        ativo_id=None,
    )
    obrigacao_imi = await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="imi",
        descricao="IMI",
        data_limite=date(2026, 5, 31),
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await db_session.commit()

    atualizadas = await _rodar_backfill(db_session)
    await db_session.commit()

    assert atualizadas == 0
    await db_session.refresh(obrigacao_extracao)
    await db_session.refresh(obrigacao_imi)
    assert obrigacao_extracao.ativo_id is None
    assert obrigacao_imi.ativo_id is None


@pytest.mark.asyncio
async def test_backfill_seguido_de_sincronizacao_nao_duplica_obrigacao_pre_existente(db_session):
    # Regressão do finding do reviewer: sem este backfill, uma Obrigacao pré-existente com
    # ativo_id=NULL não seria reconhecida por existe_obrigacao(..., ativo_id=<uuid real>)
    # (NULL nunca é igual a um uuid em SQL) e sincronizar_obrigacoes_ativo criaria um
    # duplicado na corrida seguinte do job_obrigacoes. Reproduz o cenário: cria a obrigação
    # "antiga" (ativo_id=None), corre o backfill, e depois corre a sincronização outra vez
    # para confirmar que já não duplica.
    titular = await titular_repo.criar_titular(db_session, nome="Elsa", tipo="proprio")
    matricula = date(2022, 3, 10)
    veiculo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=matricula
    )
    referencia = date(2026, 3, 1)
    data_inspecao = calcular_proxima_inspecao(matricula, referencia=referencia)
    data_iuc = calcular_proxima_data_iuc(matricula, referencia=referencia)

    await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção periódica obrigatória — Corsa",
        data_limite=data_inspecao,
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="iuc",
        descricao="Pagamento do IUC — Corsa",
        data_limite=data_iuc,
        origem="regra",
        titular_id=titular.id,
        ativo_id=None,
    )
    await db_session.commit()

    atualizadas = await _rodar_backfill(db_session)
    await db_session.commit()
    assert atualizadas == 2

    await sincronizar_obrigacoes_ativo(
        db_session,
        titular_id=titular.id,
        matricula=matricula,
        referencia=referencia,
        ativo_id=veiculo.id,
        ativo_nome=veiculo.nome,
    )

    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    minhas = [o for o in pendentes if o.titular_id == titular.id]
    # continuam 2 (as duas já backfilled), NÃO 4 — a sincronização reconheceu-as como já
    # existentes em vez de as tratar como novas.
    assert len(minhas) == 2
    assert sorted(o.tipo for o in minhas) == ["inspecao", "iuc"]
    assert all(o.ativo_id == veiculo.id for o in minhas)
