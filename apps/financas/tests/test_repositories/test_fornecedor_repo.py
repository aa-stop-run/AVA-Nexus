from datetime import date
from decimal import Decimal

import pytest

from ava.repositories.fornecedor_repo import listar_com_despesas, marcar_parser_nivel0, obter_ou_criar


@pytest.mark.asyncio
async def test_obter_ou_criar_e_idempotente_por_nome(db_session):
    primeiro = await obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    segundo = await obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")

    assert primeiro.id == segundo.id

    await marcar_parser_nivel0(db_session, primeiro.id)
    assert primeiro.tem_parser_nivel0 is True


@pytest.mark.asyncio
async def test_listar_com_despesas_so_inclui_fornecedores_com_saida_registada(db_session):
    from ava.repositories import movimento_repo
    from ava.repositories.movimento_repo import LinhaNova

    com_despesa = await obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    sem_despesa = await obter_ou_criar(db_session, nome="Fornecedor Novo", tipo="outro")
    await db_session.commit()

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="documento", fornecedor_id=com_despesa.id, linhas=[LinhaNova(valor=Decimal("50.00"))],
    )
    await db_session.commit()

    fornecedores = await listar_com_despesas(db_session)

    nomes = [f.nome for f in fornecedores]
    assert "EDP" in nomes
    assert "Fornecedor Novo" not in nomes


@pytest.mark.asyncio
async def test_listar_com_despesas_ignora_fornecedor_so_com_entradas(db_session):
    # Mesmo cuidado dos testes de historico_valores_fornecedor: um reembolso (entrada) do
    # fornecedor não conta como despesa -- sem o filtro tipo == "saida", um fornecedor que só
    # reembolsou (nunca cobrou nada) apareceria na lista sem despesa nenhuma para mostrar.
    from ava.repositories import movimento_repo
    from ava.repositories.movimento_repo import LinhaNova

    fornecedor = await obter_ou_criar(db_session, nome="Insurance Co.", tipo="outro")
    await db_session.commit()

    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("100.00"), data=date(2026, 7, 1),
        origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal("100.00"))],
    )
    await db_session.commit()

    fornecedores = await listar_com_despesas(db_session)

    assert fornecedor.nome not in [f.nome for f in fornecedores]


@pytest.mark.asyncio
async def test_listar_com_despesas_ordena_por_nome(db_session):
    from ava.repositories import movimento_repo
    from ava.repositories.movimento_repo import LinhaNova

    zebra = await obter_ou_criar(db_session, nome="Zebra Lda", tipo="outro")
    alfa = await obter_ou_criar(db_session, nome="Alfa Lda", tipo="outro")
    await db_session.commit()

    for fornecedor in (zebra, alfa):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal("10.00"), data=date(2026, 7, 1),
            origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal("10.00"))],
        )
    await db_session.commit()

    fornecedores = await listar_com_despesas(db_session)

    assert [f.nome for f in fornecedores] == ["Alfa Lda", "Zebra Lda"]
