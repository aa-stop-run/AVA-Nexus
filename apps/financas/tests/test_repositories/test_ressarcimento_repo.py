"""Testes de ressarcimento_repo — o grupo que liga um reembolso à despesa que cobre.

Ver docs/superpowers/specs/2026-08-14-ressarcimento-design.md.
"""

from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import ressarcimento_repo
from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta

DIA = date(2026, 8, 1)


@pytest.mark.asyncio
async def test_resumo_de_grupo_com_uma_despesa_e_um_reembolso(db_session):
    # O caso real do utilizador: uma consulta reembolsada pelo seguro.
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    resultado = await ressarcimento_repo.resumo(db_session, grupo.id)

    assert resultado.despesas == Decimal("80.00")
    assert resultado.reembolsos == Decimal("50.00")
    assert resultado.liquido == Decimal("30.00")
    assert resultado.n_despesas == 1


@pytest.mark.asyncio
async def test_resumo_de_grupo_com_duas_despesas(db_session):
    # A ambiguidade que a spec §3.2 descreve: sem repartição, não há como saber quanto do
    # reembolso cobre cada uma — mas o resumo do GRUPO continua calculável sem ambiguidade.
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    medicamentos = await criar_categoria(db_session, nome="Medicamentos", tipo="despesa", natureza="variavel")
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="50.00",
        data=DIA, categoria_id=medicamentos.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="100.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    resultado = await ressarcimento_repo.resumo(db_session, grupo.id)

    assert resultado.despesas == Decimal("130.00")
    assert resultado.reembolsos == Decimal("100.00")
    assert resultado.liquido == Decimal("30.00")
    assert resultado.n_despesas == 2


@pytest.mark.asyncio
async def test_resumo_de_grupo_so_com_reembolso_sem_despesa_ainda(db_session):
    # "às vezes recebo o reembolso antes da despesa" — o grupo existe e é calculável mesmo vazio
    # do lado da despesa.
    titular, conta = await criar_titular_e_conta(db_session)
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    resultado = await ressarcimento_repo.resumo(db_session, grupo.id)

    assert resultado.despesas == Decimal("0")
    assert resultado.reembolsos == Decimal("50.00")
    assert resultado.n_despesas == 0


@pytest.mark.asyncio
async def test_resumo_nao_filtra_por_data_e_soma_o_grupo_inteiro(db_session):
    # n_despesas é uma propriedade do GRUPO, não do período consultado depois (spec §3.3) — este
    # teste liga uma despesa de Julho e um reembolso de Agosto e confirma que o resumo os soma
    # os dois, sem qualquer filtro de data.
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date(2026, 7, 15), categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=date(2026, 8, 10), categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    resultado = await ressarcimento_repo.resumo(db_session, grupo.id)

    assert resultado.n_despesas == 1
    assert resultado.liquido == Decimal("30.00")


@pytest.mark.asyncio
async def test_listar_recentes_devolve_grupo_com_o_seu_resumo(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    recentes = await ressarcimento_repo.listar_recentes(db_session)

    assert len(recentes) == 1
    grupo_devolvido, resumo_devolvido = recentes[0]
    assert grupo_devolvido.id == grupo.id
    assert resumo_devolvido.despesas == Decimal("80.00")
    assert resumo_devolvido.n_despesas == 1


@pytest.mark.asyncio
async def test_listar_recentes_ignora_grupos_fora_da_janela(db_session):
    # Controlo positivo obrigatório ao lado do negativo: um grupo DENTRO da janela continua a
    # aparecer no mesmo pedido em que o de fora não aparece — sem isto, uma lista sempre vazia
    # passaria este teste por acidente.
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")

    grupo_antigo = await ressarcimento_repo.criar(db_session)
    await db_session.flush()
    from sqlalchemy import update

    from ava.models.ressarcimento import Ressarcimento
    await db_session.execute(
        update(Ressarcimento).where(Ressarcimento.id == grupo_antigo.id)
        .values(criado_em=date(2020, 1, 1))
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="10.00",
        data=date(2020, 1, 1), categoria_id=consultas.id, ressarcimento_id=grupo_antigo.id,
    )

    grupo_recente = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo_recente.id,
    )
    await db_session.commit()

    recentes = await ressarcimento_repo.listar_recentes(db_session, dias=90)

    ids_devolvidos = {grupo.id for grupo, _ in recentes}
    assert grupo_recente.id in ids_devolvidos
    assert grupo_antigo.id not in ids_devolvidos


@pytest.mark.asyncio
async def test_listar_recentes_exclui_grupos_vazios(db_session):
    """Grupos sem nenhuma linha ligada não aparecem em listar_recentes,
    impedindo poluição do seletor durante 90 dias."""
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")

    # Cria um grupo vazio (sem ligar nenhuma linha)
    grupo_vazio = await ressarcimento_repo.criar(db_session)

    # Cria um grupo com uma linha ligada
    grupo_com_linha = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo_com_linha.id,
    )
    await db_session.commit()

    recentes = await ressarcimento_repo.listar_recentes(db_session)

    ids_devolvidos = {grupo.id for grupo, _ in recentes}
    assert grupo_com_linha.id in ids_devolvidos
    assert grupo_vazio.id not in ids_devolvidos


@pytest.mark.asyncio
async def test_listar_recentes_inclui_grupo_com_so_reembolso(db_session):
    """Grupo com apenas um reembolso (sem despesa ainda) aparece em listar_recentes,
    confirmando que o filtro é sobre 'tem linhas', não 'tem dos dois lados'."""
    titular, conta = await criar_titular_e_conta(db_session)
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    recentes = await ressarcimento_repo.listar_recentes(db_session)

    ids_devolvidos = {grupo.id for grupo, _ in recentes}
    assert grupo.id in ids_devolvidos
