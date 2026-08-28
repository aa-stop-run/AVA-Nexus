from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, movimento_repo, titular_repo
from ava.repositories.movimento_repo import LinhaNova


@pytest.mark.asyncio
async def test_criar_e_listar_pendentes(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=0, dados_extraidos={}
    )

    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 1),
        valor=Decimal("-45.67"),
        descricao="DD EDP",
    )

    pendentes = await linha_extrato_repo.listar_pendentes(db_session)
    assert len(pendentes) == 1
    assert pendentes[0].valor == Decimal("-45.67")


@pytest.mark.asyncio
async def test_marcar_conciliada_revisao_manual_e_ignorado(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=2, nivel_extracao=0, dados_extraidos={}
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("10.00"),
        data=date(2026, 7, 2),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("10.00"))],
    )

    m1 = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 2), valor=Decimal("-10.00")
    )
    m2 = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 3), valor=Decimal("-20.00")
    )
    m3 = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 4), valor=Decimal("-30.00")
    )

    await linha_extrato_repo.marcar_conciliada(db_session, m1.id, movimento.id)
    await linha_extrato_repo.marcar_revisao_manual(db_session, m2.id)
    await linha_extrato_repo.marcar_ignorado(db_session, m3.id)

    assert (await linha_extrato_repo.obter_por_id(db_session, m1.id)).estado == "conciliado"
    assert (await linha_extrato_repo.obter_por_id(db_session, m2.id)).estado == "revisao_manual"
    assert (await linha_extrato_repo.obter_por_id(db_session, m3.id)).estado == "ignorado"
    # a ligação em si vive em movimento.linha_extrato_id — uma só direção (ver docstring de
    # marcar_conciliada), o que torna estruturalmente impossível o antigo estado em que
    # transacao_id e rendimento_id podiam estar ambos preenchidos na mesma linha.
    movimento_ligado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert movimento_ligado.linha_extrato_id == m1.id

    em_revisao = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert [m.id for m in em_revisao] == [m2.id]


@pytest.mark.asyncio
async def test_listar_em_revisao_manual_filtra_por_busca_valor_e_data(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=10, nivel_extracao=0, dados_extraidos={}
    )

    async def _linha(data, valor, descricao):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=conta.id, documento_id=documento.id, data=data, valor=Decimal(valor),
            descricao=descricao,
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
        return linha

    supermercado = await _linha(date(2026, 7, 5), "-50.00", "COMPRA CONTINENTE 123")
    farmacia = await _linha(date(2026, 7, 10), "-8.00", "FARMACIA CENTRAL")
    salario = await _linha(date(2026, 7, 1), "1500.00", "SALARIO EMPRESA X")

    # busca (case-insensitive, substring) — só a descrição que contém o termo.
    resultado = await linha_extrato_repo.listar_em_revisao_manual(db_session, busca="continente")
    assert [l.id for l in resultado] == [supermercado.id]

    # valor_min/max comparam o valor ABSOLUTO — apanha tanto despesa como rendimento se caírem
    # no intervalo, o sinal não faz parte do que o utilizador está a procurar.
    resultado = await linha_extrato_repo.listar_em_revisao_manual(db_session, valor_min=Decimal("10"))
    assert {l.id for l in resultado} == {supermercado.id, salario.id}

    resultado = await linha_extrato_repo.listar_em_revisao_manual(db_session, valor_max=Decimal("10"))
    assert [l.id for l in resultado] == [farmacia.id]

    # intervalo de datas.
    resultado = await linha_extrato_repo.listar_em_revisao_manual(
        db_session, data_inicio=date(2026, 7, 3), data_fim=date(2026, 7, 8)
    )
    assert [l.id for l in resultado] == [supermercado.id]

    # filtros combinam-se em AND.
    resultado = await linha_extrato_repo.listar_em_revisao_manual(
        db_session, busca="farmacia", valor_max=Decimal("100")
    )
    assert [l.id for l in resultado] == [farmacia.id]
