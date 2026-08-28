from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ava.ingestion.casamento import casar_linha
from ava.ingestion.reconciliacao import reconciliar_linhas_pendentes
from ava.models.movimento import Movimento
from ava.repositories import linha_extrato_repo, movimento_repo
from tests.fabricas import (
    criar_conta,
    criar_linha_extrato,
    criar_movimento_manual,
    criar_titular_e_conta,
    criar_transferencia,
)


@pytest.mark.asyncio
async def test_casa_um_movimento_manual_com_a_linha_do_extrato(db_session):
    # O caso central: o utilizador registou a despesa, o extrato traz a mesma. Uma so, nao duas.
    titular, conta = await criar_titular_e_conta(db_session)
    movimento = await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                              valor="20.00", data=date(2026, 8, 1), descricao="Tabaco")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.00",
                                       data=date(2026, 8, 3), descricao="PAGAMENTO SERVICOS")
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True
    await db_session.refresh(movimento)
    assert movimento.linha_extrato_id == linha.id
    assert movimento.descricao == "Tabaco"  # a descricao do utilizador sobrevive
    assert movimento.origem == "manual"     # origem nao muda ao confirmar
    assert linha.estado == "conciliado"  # contrato de casar_linha: casou E marcou a linha

    todos = await db_session.execute(select(Movimento).where(Movimento.conta_id == conta.id))
    assert len(todos.scalars().all()) == 1


@pytest.mark.asyncio
async def test_dois_cafes_iguais_casam_com_duas_linhas_iguais(db_session):
    # Emparelhamento em grupo: qualquer par da o mesmo resultado, por isso nao vai a revisao.
    # Guarda o min(N, M): uma implementacao que ligasse as DUAS linhas ao MESMO movimento
    # passaria em "True is True", por isso o teste tem de afirmar que sao dois movimentos
    # distintos, um por linha.
    titular, conta = await criar_titular_e_conta(db_session)
    movimentos = [
        await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                      valor="2.50", data=date(2026, 8, 1), descricao="Cafe")
        for _ in range(2)
    ]
    l1 = await criar_linha_extrato(db_session, conta=conta, valor="-2.50", data=date(2026, 8, 2))
    l2 = await criar_linha_extrato(db_session, conta=conta, valor="-2.50", data=date(2026, 8, 2))
    await db_session.commit()

    assert await casar_linha(db_session, l1) is True
    assert await casar_linha(db_session, l2) is True

    for movimento in movimentos:
        await db_session.refresh(movimento)
    assert {m.linha_extrato_id for m in movimentos} == {l1.id, l2.id}


@pytest.mark.asyncio
async def test_um_movimento_e_duas_linhas_deixa_uma_por_casar(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                  valor="2.50", data=date(2026, 8, 1), descricao="Cafe")
    l1 = await criar_linha_extrato(db_session, conta=conta, valor="-2.50", data=date(2026, 8, 2))
    l2 = await criar_linha_extrato(db_session, conta=conta, valor="-2.50", data=date(2026, 8, 2))
    await db_session.commit()

    assert await casar_linha(db_session, l1) is True
    assert await casar_linha(db_session, l2) is False


@pytest.mark.asyncio
async def test_nao_casa_por_um_centimo_de_diferenca(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                  valor="20.00", data=date(2026, 8, 1), descricao="Tabaco")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.01", data=date(2026, 8, 2))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is False


@pytest.mark.asyncio
async def test_nao_casa_fora_da_janela_dos_sete_dias(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                  valor="20.00", data=date(2026, 8, 1), descricao="Tabaco")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 9))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is False


@pytest.mark.asyncio
async def test_a_janela_e_simetrica(db_session):
    # A linha pode ser ANTERIOR ao movimento: o utilizador pode datar pelo talao e ficar aquem.
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                  valor="20.00", data=date(2026, 8, 8), descricao="Tabaco")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 3))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True


@pytest.mark.asyncio
async def test_escolhe_o_candidato_de_data_mais_proxima(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    longe = await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                          valor="20.00", data=date(2026, 8, 1), descricao="Longe")
    perto = await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                          valor="20.00", data=date(2026, 8, 4), descricao="Perto")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 5))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True
    await db_session.refresh(perto)
    await db_session.refresh(longe)
    assert perto.linha_extrato_id == linha.id
    assert longe.linha_extrato_id is None


@pytest.mark.asyncio
async def test_nao_recasa_um_movimento_ja_confirmado(db_session):
    # Sem isto, um segundo extrato que repetisse a linha reescrevia a ligacao em silencio.
    titular, conta = await criar_titular_e_conta(db_session)
    movimento = await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                              valor="20.00", data=date(2026, 8, 1), descricao="Tabaco")
    l1 = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 2))
    await db_session.commit()
    await casar_linha(db_session, l1)

    l2 = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 3))
    await db_session.commit()
    assert await casar_linha(db_session, l2) is False
    await db_session.refresh(movimento)
    assert movimento.linha_extrato_id == l1.id


@pytest.mark.asyncio
async def test_nao_casa_com_movimento_sem_conta(db_session):
    # Exclusao deliberada (spec §6.4): a fatura da EDP entra sem conta_id. Sem conta nao ha lado
    # onde casar, e casa-la com uma linha qualquer do mesmo valor seria inventar uma ligacao.
    titular, conta = await criar_titular_e_conta(db_session)
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("83.39"), data=date(2026, 8, 1),
        origem="documento", descricao="EDP", conta_id=None, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("83.39"), categoria_id=None)],
    )
    linha = await criar_linha_extrato(
        db_session, conta=conta, valor="-83.39", data=date(2026, 8, 2)
    )
    await db_session.commit()

    assert await casar_linha(db_session, linha) is False


@pytest.mark.asyncio
async def test_linha_positiva_casa_pelo_lado_de_destino(db_session):
    # Uma transferencia a entrar confirma-se por linha_extrato_destino_id (spec §4.1).
    titular, ordem = await criar_titular_e_conta(db_session, nome="Ordem")
    credito = await criar_conta(db_session, titular=titular, tipo="emprestimo", nome="Credito")
    movimento = await criar_transferencia(db_session, titular=titular, origem=ordem,
                                           destino=credito, valor="460.00", data=date(2026, 8, 1),
                                           manual=True)
    linha = await criar_linha_extrato(db_session, conta=credito, valor="460.00", data=date(2026, 8, 3))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True
    await db_session.refresh(movimento)
    assert movimento.linha_extrato_destino_id == linha.id
    assert movimento.linha_extrato_id is None
    assert linha.estado == "conciliado"  # contrato de casar_linha: casou E marcou a linha


@pytest.mark.asyncio
async def test_linha_positiva_casa_com_entrada_manual(db_session):
    # O ramo tipo="entrada" com linha positiva nao tinha teste nenhum: criar_movimento_manual so
    # produz "saida", e o unico teste de linha positiva era o da transferencia. Sem isto, um
    # salario registado a mao nunca confirmaria e contaria em dobro (o mesmo problema que esta
    # tarefa inteira existe para evitar, so que do lado da entrada).
    titular, conta = await criar_titular_e_conta(db_session)
    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("1500.00"), data=date(2026, 8, 1),
        origem="manual", descricao="Salario", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("1500.00"), categoria_id=None)],
    )
    linha = await criar_linha_extrato(db_session, conta=conta, valor="1500.00", data=date(2026, 8, 3))
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True
    await db_session.refresh(movimento)
    assert movimento.linha_extrato_id == linha.id
    assert movimento.linha_extrato_destino_id is None


@pytest.mark.asyncio
async def test_reconciliar_linhas_pendentes_confirma_movimento_manual_em_vez_de_duplicar(db_session):
    # Integracao ponta a ponta: conciliar_uma_linha chama casar_linha ANTES de tudo o resto
    # (reconciliacao.py). Os movimentos usados em test_reconciliacao.py sao sempre criados SEM
    # conta_id, por isso nunca exercitam este ramo por acidente - aqui a linha e o movimento
    # partilham conta_id de proposito, para provar que o caminho de producao (nao so a chamada
    # direta a casar_linha) confirma em vez de duplicar.
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(db_session, titular=titular, conta=conta,
                                  valor="20.00", data=date(2026, 8, 1), descricao="Tabaco")
    linha = await criar_linha_extrato(db_session, conta=conta, valor="-20.00", data=date(2026, 8, 3))
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "conciliado"
    resultado = await db_session.execute(select(Movimento).where(Movimento.conta_id == conta.id))
    assert len(resultado.scalars().all()) == 1


@pytest.mark.asyncio
async def test_casa_um_movimento_importado_de_ficheiro(db_session):
    # Sem isto, o extrato do mes seguinte criaria um duplicado de cada movimento importado --
    # a dupla contagem que a spec de 2026-08-08 existe para impedir, por uma porta nova.
    titular, conta = await criar_titular_e_conta(db_session)
    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("65.89"), data=date(2026, 8, 1),
        origem="ficheiro", descricao="01/08 COMPRA ELEC 2311263/46 MAREC",
        conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("65.89"), categoria_id=None)],
    )
    linha = await criar_linha_extrato(
        db_session, conta=conta, valor="-65.89", data=date(2026, 8, 3), descricao="COMPRA ELEC"
    )
    await db_session.commit()

    assert await casar_linha(db_session, linha) is True
    await db_session.refresh(movimento)
    assert movimento.linha_extrato_id == linha.id
    assert linha.estado == "conciliado"
