"""Ressarcimento em margem_estrutural — spec 2026-08-14 §4.1."""

from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import ressarcimento_repo
from ava.repositories.margem_repo import margem_estrutural
from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta

DE = date(2026, 8, 1)
ATE = date(2026, 8, 31)
DIA = date(2026, 8, 15)


@pytest.mark.asyncio
async def test_despesa_de_grupo_simples_usa_o_liquido(db_session):
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

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_variavel == Decimal("30.00")
    assert m.rendimento_extraordinario == Decimal("0")
    assert m.margem == Decimal("-30.00")


@pytest.mark.asyncio
async def test_despesa_de_grupo_com_duas_despesas_usa_o_valor_bruto(db_session):
    # Controlo negativo: confirma que a ambiguidade realmente impede o desconto, em vez de o
    # código aplicar silenciosamente uma regra de repartição que ninguém pediu.
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

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_variavel == Decimal("130.00")
    # E o reembolso continua visível como rendimento extraordinário — não desaparece sem rasto.
    assert m.rendimento_extraordinario == Decimal("100.00")


@pytest.mark.asyncio
async def test_reembolso_sem_despesa_no_grupo_continua_extraordinario(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")

    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=DIA, categoria_id=reembolsos.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.rendimento_extraordinario == Decimal("50.00")


@pytest.mark.asyncio
async def test_despesa_de_julho_reembolso_de_agosto_ligados_ao_mesmo_grupo(db_session):
    # A consequência temporal da spec §3.4: a margem de Julho (recalculada agora) usa o
    # líquido; a margem de Agosto não ganha nem perde nada com o reembolso.
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

    margem_julho = await margem_estrutural(
        db_session, de=date(2026, 7, 1), ate=date(2026, 7, 31)
    )
    margem_agosto = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert margem_julho.despesa_variavel == Decimal("30.00")
    assert margem_agosto.despesa_variavel == Decimal("0")
    assert margem_agosto.rendimento_extraordinario == Decimal("0")
