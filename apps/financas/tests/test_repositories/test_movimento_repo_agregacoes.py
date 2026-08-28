import uuid
from datetime import date
from decimal import Decimal

from ava.repositories import conta_repo, movimento_repo, titular_repo


async def test_listar_por_conta_devolve_so_movimentos_dessa_conta(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta_a = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta A"
    )
    conta_b = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Conta B"
    )
    await db_session.flush()

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("10.00"), data=date(2026, 7, 1),
        origem="manual", descricao="da conta A", conta_id=conta_a.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("10.00"), categoria_id=None)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("20.00"), data=date(2026, 7, 2),
        origem="manual", descricao="da conta B", conta_id=conta_b.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("20.00"), categoria_id=None)],
    )
    await db_session.commit()

    resultado = await movimento_repo.listar_por_conta(db_session, conta_a.id)

    assert len(resultado) == 1
    assert resultado[0].descricao == "da conta A"


async def test_totais_por_categoria_agrupa_e_soma_por_categoria(db_session):
    from ava.repositories import categoria_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Grupo Teste")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Categoria Teste", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()

    for valor in (Decimal("10.00"), Decimal("15.00")):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=valor, data=date(2026, 7, 5),
            origem="manual", descricao="teste", conta_id=conta.id, registado_por=titular.id,
            linhas=[movimento_repo.LinhaNova(valor=valor, categoria_id=categoria.id)],
        )
    await db_session.commit()

    resultado = await movimento_repo.totais_por_categoria(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )

    assert len(resultado) == 1
    grupo_result, categoria_result, total = resultado[0]
    assert grupo_result.nome == "Grupo Teste"
    assert categoria_result.nome == "Categoria Teste"
    assert total == Decimal("25.00")


async def test_totais_por_categoria_exclui_movimentos_fora_do_periodo(db_session):
    from ava.repositories import categoria_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste2", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta2"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Grupo Fora")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Categoria Fora", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("99.00"), data=date(2026, 6, 30),
        origem="manual", descricao="fora do periodo", conta_id=conta.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("99.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    resultado = await movimento_repo.totais_por_categoria(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )

    assert resultado == []
