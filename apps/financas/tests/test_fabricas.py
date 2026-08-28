from datetime import date
from decimal import Decimal

import pytest

from tests.fabricas import (
    criar_conta,
    criar_linha_extrato,
    criar_movimento_manual,
    criar_titular_e_conta,
    criar_transferencia,
)


@pytest.mark.asyncio
async def test_movimento_manual_fica_por_confirmar(db_session):
    # A propriedade de que todo o casamento depende: sem linha_extrato_id, esta por confirmar.
    titular, conta = await criar_titular_e_conta(db_session)
    movimento = await criar_movimento_manual(
        db_session, titular=titular, conta=conta, valor="20.00", data=date(2026, 8, 1),
        descricao="Tabaco",
    )
    await db_session.commit()

    assert movimento.linha_extrato_id is None
    assert movimento.origem == "manual"
    assert movimento.valor == Decimal("20.00")


@pytest.mark.asyncio
async def test_transferencia_toca_as_duas_contas(db_session):
    titular, ordem = await criar_titular_e_conta(db_session, nome="Ordem")
    credito = await criar_conta(db_session, titular=titular, tipo="emprestimo", nome="Credito")
    transferencia = await criar_transferencia(
        db_session, titular=titular, origem=ordem, destino=credito,
        valor="460.00", data=date(2026, 8, 5),
    )
    await db_session.commit()

    assert transferencia.conta_id == ordem.id
    assert transferencia.conta_destino_id == credito.id


@pytest.mark.asyncio
async def test_linha_de_extrato_negativa_e_uma_saida(db_session):
    _, conta = await criar_titular_e_conta(db_session)
    linha = await criar_linha_extrato(
        db_session, conta=conta, valor="-20.00", data=date(2026, 8, 3)
    )
    await db_session.commit()

    assert linha.valor == Decimal("-20.00")
