"""Ressarcimento em totais_por_categoria — spec 2026-08-14 §4.2, §4.3.

totais_por_categoria alimenta tanto a despesa por categoria/orçamentos (tipo="saida") como a
lista de rendimentos do dashboard, de onde "Rendimento extraordinário" é filtrada (tipo="entrada")
— por isso um único ficheiro de teste cobre as duas chamadas.
"""

from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import movimento_repo, ressarcimento_repo
from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta

INICIO = date(2026, 8, 1)
FIM = date(2026, 8, 31)
DIA = date(2026, 8, 15)


@pytest.mark.asyncio
async def test_despesa_por_categoria_usa_liquido_de_grupo_simples(db_session):
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

    despesas = await movimento_repo.totais_por_categoria(
        db_session, inicio=INICIO, fim=FIM, tipo="saida"
    )

    assert len(despesas) == 1
    _, categoria, total = despesas[0]
    assert categoria.nome == "Consultas"
    assert total == Decimal("30.00")


@pytest.mark.asyncio
async def test_despesa_por_categoria_de_grupo_com_duas_despesas_fica_bruta(db_session):
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

    despesas = await movimento_repo.totais_por_categoria(
        db_session, inicio=INICIO, fim=FIM, tipo="saida"
    )

    totais_por_nome = {categoria.nome: total for _, categoria, total in despesas}
    assert totais_por_nome["Consultas"] == Decimal("80.00")
    assert totais_por_nome["Medicamentos"] == Decimal("50.00")


@pytest.mark.asyncio
async def test_reembolso_de_grupo_simples_nao_aparece_em_rendimentos(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")
    salario = await criar_categoria(db_session, nome="Salário", tipo="receita", natureza="recorrente")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=DIA, categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    # Controlo positivo: um rendimento NÃO ligado a nenhum grupo continua a aparecer, no mesmo
    # pedido em que o reembolso ligado desaparece.
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="1500.00",
        data=DIA, categoria_id=salario.id,
    )
    await db_session.commit()

    rendimentos = await movimento_repo.totais_por_categoria(
        db_session, inicio=INICIO, fim=FIM, tipo="entrada"
    )

    nomes = {categoria.nome for _, categoria, _ in rendimentos}
    assert "Reembolsos" not in nomes
    assert "Salário" in nomes


@pytest.mark.asyncio
async def test_reembolso_de_grupo_com_duas_despesas_continua_em_rendimentos(db_session):
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

    rendimentos = await movimento_repo.totais_por_categoria(
        db_session, inicio=INICIO, fim=FIM, tipo="entrada"
    )

    totais_por_nome = {categoria.nome: total for _, categoria, total in rendimentos}
    assert totais_por_nome["Reembolsos"] == Decimal("100.00")


@pytest.mark.asyncio
async def test_transferencia_com_categoria_nao_e_afetada_por_ressarcimento(db_session):
    # totais_por_categoria também é chamada com tipo=("saida", "transferencia") pelo dashboard —
    # uma transferência categorizada não tem ressarcimento_id (a UI não o oferece para
    # transferências) e tem de continuar a somar pelo valor bruto normalmente.
    titular, conta = await criar_titular_e_conta(db_session)
    from ava.repositories import conta_repo
    conta_poupanca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="poupanca", nome="Poupança"
    )
    amortizacao = await criar_categoria(
        db_session, nome="Amortização de capital", tipo="despesa", natureza="fixa"
    )
    from tests.fabricas import criar_transferencia
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=conta_poupanca,
        valor="200.00", data=DIA, categoria_id=amortizacao.id,
    )
    await db_session.commit()

    despesas = await movimento_repo.totais_por_categoria(
        db_session, inicio=INICIO, fim=FIM, tipo=("saida", "transferencia")
    )

    assert len(despesas) == 1
    assert despesas[0][2] == Decimal("200.00")
