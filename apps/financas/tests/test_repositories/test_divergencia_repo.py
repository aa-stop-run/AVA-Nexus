"""Testes de ava.repositories.divergencia_repo.listar_divergencias.

Cobre o Achado 3 da revisão final da spec 2026-08-08: uma âncora MANUAL não é uma medição que o
razão tenha de explicar — é uma declaração de reposição, o mecanismo de "novo ponto de partida"
que a §11 descreve. Sem o filtro, o dia em que o utilizador declara à mão o saldo real de uma
conta abriria sempre /reconciliacao com uma janela por conta corrigida, gritando sobre a própria
correção que ele acabou de fazer (spec §6.3: "uma lista que grita sempre não é um sinal").

Cobre também a correção da spec 2026-08-09: duas âncoras de FICHEIRO consecutivas definem uma
janela impossível de fechar por construção (a cascata de datas da §3 atribui a alguns lançamentos
uma data anterior à primeira âncora), por isso a janela cuja âncora INICIAL é de ficheiro também é
excluída — sem tocar na janela que começa num extrato e acaba num ficheiro, essa continua a
interessar.
"""

from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import divergencia_repo, saldo_historico_repo
from tests.fabricas import criar_titular_e_conta


@pytest.mark.asyncio
async def test_janela_que_termina_numa_ancora_manual_nao_aparece(db_session):
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("1000.00"),
    )
    # Âncora manual mais recente: o utilizador está a corrigir um saldo que sabe estar errado --
    # sem movimentos nenhuns a explicar a diferença de 300.00, a janela fecharia sempre em
    # divergência, e essa "divergência" seria exatamente a correção que ele acabou de fazer.
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 9), valor=Decimal("1300.00"), origem="manual",
    )
    await db_session.commit()

    divergencias = await divergencia_repo.listar_divergencias(db_session)

    assert divergencias == []


@pytest.mark.asyncio
async def test_janela_que_termina_numa_ancora_de_extrato_continua_a_aparecer(db_session):
    # Contraste com o teste acima: só a ORIGEM da âncora final muda (extrato em vez de manual).
    # Prova que o filtro discrimina por origem -- não que passou a ignorar todas as janelas.
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("1000.00"),
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 9), valor=Decimal("1300.00"), origem="extrato",
    )
    await db_session.commit()

    divergencias = await divergencia_repo.listar_divergencias(db_session)

    assert len(divergencias) == 1
    divergencia = divergencias[0]
    assert divergencia.conta.id == conta.id
    assert divergencia.declarado == Decimal("300.00")
    assert divergencia.derivado == Decimal("0.00")
    assert divergencia.diferenca == Decimal("300.00")


@pytest.mark.asyncio
async def test_janela_entre_duas_ancoras_de_ficheiro_nao_aparece(db_session):
    """Duas fotografias provisórias não delimitam um período mensurável (spec 2026-08-09, §2.1 e
    §3): a cascata de datas atribui a alguns lançamentos entre as duas importações uma data
    ANTERIOR à primeira âncora de ficheiro, por isso o `fluxo_entre` nunca os conta e a janela
    nunca fecha -- não porque falte nada no razão, mas porque a própria janela é impossível de
    fechar por construção. Sem movimentos nenhuns a explicar o salto de 1000 para 1300, é
    exatamente esse buraco de construção que apareceria como divergência."""
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("1000.00"), origem="ficheiro",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 9), valor=Decimal("1300.00"), origem="ficheiro",
    )
    await db_session.commit()

    divergencias = await divergencia_repo.listar_divergencias(db_session)

    assert divergencias == []


@pytest.mark.asyncio
async def test_janela_de_extrato_para_ficheiro_continua_a_aparecer(db_session):
    """Contraste com o teste acima: a âncora INICIAL passa a ser de extrato (definitiva), só a
    final continua a ser de ficheiro. Prova que a exclusão é pela origem da âncora inicial, não
    por acaso -- e que a janela que realmente interessa (o que aconteceu desde o último fecho do
    banco) continua verificada."""
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("1000.00"), origem="extrato",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 9), valor=Decimal("1300.00"), origem="ficheiro",
    )
    await db_session.commit()

    divergencias = await divergencia_repo.listar_divergencias(db_session)

    assert len(divergencias) == 1
    divergencia = divergencias[0]
    assert divergencia.conta.id == conta.id
    assert divergencia.declarado == Decimal("300.00")
    assert divergencia.derivado == Decimal("0.00")
    assert divergencia.diferenca == Decimal("300.00")


@pytest.mark.asyncio
async def test_janela_entre_duas_ancoras_de_extrato_continua_a_aparecer(db_session):
    """O caso normal, sem nenhuma origem provisória envolvida: duas âncoras de extrato são as
    duas medições mais fortes que existem, e a janela entre elas tem de continuar verificada.
    Garante que a nova exclusão da âncora inicial de ficheiro não afeta o caminho comum."""
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("1000.00"), origem="extrato",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 9), valor=Decimal("1300.00"), origem="extrato",
    )
    await db_session.commit()

    divergencias = await divergencia_repo.listar_divergencias(db_session)

    assert len(divergencias) == 1
    divergencia = divergencias[0]
    assert divergencia.conta.id == conta.id
    assert divergencia.declarado == Decimal("300.00")
    assert divergencia.derivado == Decimal("0.00")
    assert divergencia.diferenca == Decimal("300.00")
