import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from ava.ingestion.reconciliacao import (
    categorizar_transferencia,
    conciliar_amortizacoes_de_credito,
    desfazer_movimento,
    ignorar_linha,
    reconciliar_linhas_pendentes,
    resolver_como_despesa,
    resolver_como_rendimento,
    resolver_como_transferencia,
    verificar_movimentos_sem_extrato,
)
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.repositories import (
    ativo_repo,
    categoria_repo,
    conta_repo,
    documento_repo,
    linha_extrato_repo,
    movimento_repo,
    titular_repo,
)
from ava.repositories.movimento_repo import LinhaNova


async def _categoria(db_session, grupo_nome="Alimentação", nome="Supermercado", tipo="despesa"):
    grupo = await categoria_repo.criar_grupo(db_session, nome=grupo_nome)
    natureza = "extraordinario" if tipo == "receita" else "variavel"
    return await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=nome, tipo=tipo, natureza=natureza
    )


@pytest.mark.asyncio
async def test_linha_de_saida_casa_com_movimento_unico(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    categoria = await _categoria(db_session)
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5), valor=Decimal("-45.67")
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("45.67"),
        data=date(2026, 7, 3),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("45.67"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "conciliado"
    movimento_lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert movimento_lido.linha_extrato_id == linha.id


@pytest.mark.asyncio
async def test_linha_de_entrada_casa_com_movimento_unico(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    categoria = await _categoria(db_session, grupo_nome="Rendimentos", nome="Salário", tipo="receita")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=8, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5), valor=Decimal("1500.00")
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="entrada",
        valor=Decimal("1500.00"),
        data=date(2026, 7, 3),
        origem="regra",
        linhas=[LinhaNova(valor=Decimal("1500.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "conciliado"
    movimento_lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert movimento_lido.linha_extrato_id == linha.id


@pytest.mark.asyncio
async def test_linha_de_entrada_nao_casa_com_movimento_de_saida_do_mesmo_valor(db_session):
    # A direção importa: uma linha positiva (crédito) não pode casar com um movimento "saida" do
    # mesmo valor dentro da janela, mesmo que seja o único candidato desse valor. Se o filtro
    # Movimento.tipo == tipo desaparecesse de listar_candidatos_para_conciliar, este teste falharia
    # (a linha ficaria "conciliado" em vez de "revisao_manual").
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    categoria = await _categoria(db_session)
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=9, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5), valor=Decimal("300.00")
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("300.00"),
        data=date(2026, 7, 3),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("300.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "revisao_manual"
    movimento_lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert movimento_lido.linha_extrato_id is None


@pytest.mark.asyncio
async def test_linha_ambigua_nunca_adivinha(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    categoria = await _categoria(db_session)
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=2, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5), valor=Decimal("-20.00")
    )
    m1 = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("20.00"),
        data=date(2026, 7, 3),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("20.00"), categoria_id=categoria.id)],
    )
    m2 = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("20.00"),
        data=date(2026, 7, 4),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("20.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "revisao_manual"
    for mid in (m1.id, m2.id):
        movimento_lido = await movimento_repo.obter_por_id(db_session, mid)
        assert movimento_lido.linha_extrato_id is None


@pytest.mark.asyncio
async def test_conciliar_sem_candidatos_fica_em_revisao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=3, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5), valor=Decimal("-99.99")
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "revisao_manual"


@pytest.mark.asyncio
async def test_resolver_como_despesa_cria_movimento_com_a_categoria_escolhida(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, nome="Supermercado")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=4, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 6),
        valor=Decimal("-30.00"),
        descricao="COMPRA CONTINENTE",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    assert await resolver_como_despesa(db_session, linha_id=linha.id, categoria_id=cat.id) is True

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "conciliado"
    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].tipo == "saida"
    assert movimentos[0].valor == Decimal("30.00")  # sinal normalizado: valor sempre positivo
    assert movimentos[0].linhas[0].categoria_id == cat.id
    assert movimentos[0].conta_id == conta.id
    assert movimentos[0].linha_extrato_id == linha.id


@pytest.mark.asyncio
async def test_resolver_como_rendimento_normaliza_o_sinal(db_session):
    # Fix 5 (agora partilhado via _resolver): uma linha NEGATIVA resolvida como rendimento por
    # engano não pode criar um movimento negativo — isso corromperia silenciosamente os totais.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, grupo_nome="Rendimentos", nome="Salário", tipo="receita")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=5, nivel_extracao=0, dados_extraidos={}
    )
    linha_negativa = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 7),
        valor=Decimal("-200.00"),
        descricao="DD ENGANADO",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_negativa.id)
    await db_session.commit()

    assert (
        await resolver_como_rendimento(db_session, linha_id=linha_negativa.id, categoria_id=cat.id) is True
    )

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("200.00")  # positivo, nunca negativo


@pytest.mark.asyncio
async def test_ignorar_linha_nao_cria_movimento(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="poupanca", nome="Poupança"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=6, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 8),
        valor=Decimal("500.00"),
        descricao="TRANSF ENTRE CONTAS PROPRIAS",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    assert await ignorar_linha(db_session, linha_id=linha.id) is True

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "ignorado"
    assert (
        await movimento_repo.listar_por_periodo(db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31))
        == []
    )


@pytest.mark.asyncio
async def test_resolver_como_despesa_recusa_linha_de_valor_zero(db_session):
    # Achado 3 (revisão final de fecho da Fase A): uma linha_extrato de valor 0,00 (rara, mas
    # possível — ex. um estorno que anula exatamente o original) faria criar_movimento levantar
    # movimento_repo.ValorNaoPositivo, rebentando a rota /movimentos com um 500. Um movimento de
    # valor zero não tem significado financeiro real; a ação certa para o utilizador nesse caso é
    # "Ignorar" (ignorar_linha), que já existe e já funciona — resolver como despesa/rendimento deve
    # recusar de forma limpa em vez disso.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, nome="Supermercado")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=10, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 10),
        valor=Decimal("0.00"),
        descricao="ESTORNO EXATO",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    assert await resolver_como_despesa(db_session, linha_id=linha.id, categoria_id=cat.id) is False

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "revisao_manual"
    assert (
        await movimento_repo.listar_por_periodo(db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31))
        == []
    )


@pytest.mark.asyncio
async def test_as_tres_resolucoes_recusam_linha_que_nao_esta_em_revisao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session)
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=7, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 9), valor=Decimal("-10.00")
    )
    await db_session.commit()  # estado fica "pendente" — nunca passou por revisao_manual

    assert await resolver_como_despesa(db_session, linha_id=linha.id, categoria_id=cat.id) is False
    assert await resolver_como_rendimento(db_session, linha_id=linha.id, categoria_id=cat.id) is False
    assert await ignorar_linha(db_session, linha_id=linha.id) is False

    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "pendente"
    assert (
        await movimento_repo.listar_por_periodo(db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31))
        == []
    )


@pytest.mark.asyncio
async def test_resolver_como_despesa_nao_arrasta_as_linhas_do_mesmo_padrao(db_session):
    # Inverso do comportamento anterior. O bulk-apply por padrão de descrição foi removido: com
    # três veículos, atribuir um abastecimento GALP ao Audi arrastava silenciosamente os do
    # Megane e da mota (ver a spec 2026-08-06, §1). Cada linha passa a ser resolvida sozinha.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    categoria = await _categoria(db_session, grupo_nome="Transportes", nome="Fuel Type")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    primeira = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 1), valor=Decimal("-60.00"), descricao="GALP AREAS 111111",
    )
    segunda = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 5), valor=Decimal("-55.00"), descricao="GALP AREAS 222222",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, primeira.id)
    await linha_extrato_repo.marcar_revisao_manual(db_session, segunda.id)
    await db_session.commit()

    assert await resolver_como_despesa(
        db_session, linha_id=primeira.id, categoria_id=categoria.id
    ) is True

    # A segunda continua à espera de decisão própria — é o ponto todo desta mudança.
    pendentes = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert [linha.id for linha in pendentes] == [segunda.id]


@pytest.mark.asyncio
async def test_ignorar_linha_nao_ignora_as_do_mesmo_padrao(db_session):
    # Inverso do comportamento anterior, pela mesma razão de _resolver: "Ignorar" passa a actuar
    # sobre a linha escolhida, não sobre o grupo. Com a vista individual, ignorar uma linha e ver
    # cinco desaparecer seria surpreendente e irreversível pela interface.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=4, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    primeira = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 1), valor=Decimal("-10.00"), descricao="COMISSAO 555551",
    )
    segunda = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 2), valor=Decimal("-10.00"), descricao="COMISSAO 555552",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, primeira.id)
    await linha_extrato_repo.marcar_revisao_manual(db_session, segunda.id)
    await db_session.commit()

    assert await ignorar_linha(db_session, linha_id=primeira.id) is True

    pendentes = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert [linha.id for linha in pendentes] == [segunda.id]


@pytest.mark.asyncio
async def test_conciliar_uma_linha_auto_categoriza_com_padrao_ja_aprendido(db_session):
    # Depois de o utilizador categorizar manualmente uma transação de um comerciante, uma NOVA
    # linha do mesmo comerciante (ex. no mês seguinte) deve auto-categorizar-se em vez de cair
    # em revisão manual — sem candidato de movimento a conciliar nenhum.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, nome="Supermercado")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=13, nivel_extracao=0, dados_extraidos={}
    )
    linha_antiga = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 6, 5),
        valor=Decimal("-30.00"),
        descricao="COMPRA ELEC 111111 MERCADONA GONDOMAR",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_antiga.id)
    await db_session.commit()
    assert await resolver_como_despesa(db_session, linha_id=linha_antiga.id, categoria_id=cat.id) is True

    # linha nova, mês seguinte, mesmo comerciante, referência diferente, ainda "pendente"
    linha_nova = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 5),
        valor=Decimal("-42.00"),
        descricao="COMPRA ELEC 999999 MERCADONA GONDOMAR",
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_nova_lida = await linha_extrato_repo.obter_por_id(db_session, linha_nova.id)
    assert linha_nova_lida.estado == "conciliado"

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("42.00")
    assert movimentos[0].linhas[0].categoria_id == cat.id


@pytest.mark.asyncio
async def test_conciliar_uma_linha_nao_rebenta_com_valor_zero_e_padrao_ja_aprendido(db_session):
    # Achado de revisão: uma linha de valor 0,00 (ex. um estorno exato) cujo padrão de descrição
    # coincida com uma categoria já aprendida não pode tentar criar_movimento (que rejeita
    # valor<=0 com ValorNaoPositivo) — conciliar_uma_linha corre num loop sem try/except em
    # reconciliar_linhas_pendentes, por isso uma exceção aqui rebentaria o batch inteiro, não só
    # esta linha. A linha de valor zero deve cair em revisão manual como qualquer outra ambígua.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, nome="Supermercado")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=14, nivel_extracao=0, dados_extraidos={}
    )
    linha_antiga = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 6, 5),
        valor=Decimal("-30.00"),
        descricao="COMPRA ELEC 111111 MERCADONA GONDOMAR",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_antiga.id)
    await db_session.commit()
    assert await resolver_como_despesa(db_session, linha_id=linha_antiga.id, categoria_id=cat.id) is True

    # mesmo comerciante, mas valor 0,00 — não deve tentar auto-categorizar, nem rebentar
    linha_zero = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 5),
        valor=Decimal("0.00"),
        descricao="COMPRA ELEC 999999 MERCADONA GONDOMAR",
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)  # não deve levantar ValorNaoPositivo

    linha_zero_lida = await linha_extrato_repo.obter_por_id(db_session, linha_zero.id)
    assert linha_zero_lida.estado == "revisao_manual"


@pytest.mark.asyncio
async def test_duas_linhas_do_mesmo_comerciante_podem_ir_para_ativos_diferentes(db_session):
    # O objetivo da spec: dois abastecimentos no mesmo posto, um para cada carro.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    categoria = await _categoria(db_session, grupo_nome="Transportes", nome="Fuel Type")
    audi = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    megane = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Sedan 2.0 TDI", tipo="carro"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=2, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    linhas = []
    for indice, valor in ((1, Decimal("-60.00")), (2, Decimal("-55.00"))):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=conta.id, documento_id=documento.id,
            data=date(2026, 8, indice), valor=valor, descricao=f"GALP AREAS 33333{indice}",
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
        linhas.append(linha)
    await db_session.commit()

    await resolver_como_despesa(
        db_session, linha_id=linhas[0].id, categoria_id=categoria.id, ativo_id=audi.id
    )
    await resolver_como_despesa(
        db_session, linha_id=linhas[1].id, categoria_id=categoria.id, ativo_id=megane.id
    )

    resultado = await db_session.execute(select(MovimentoLinha))
    por_ativo = sorted(linha.ativo_id for linha in resultado.scalars().all())
    assert por_ativo == sorted([audi.id, megane.id])


@pytest.mark.asyncio
async def test_resolver_nao_copia_a_leitura_do_odometro_para_outra_linha(db_session):
    # Cada abastecimento tem o SEU conta-quilómetros. O bulk-apply copiava o odómetro (e a
    # quantidade) de uma linha para as outras do mesmo posto, falseando o cálculo de L/100km
    # que a página do veículo apresenta.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    categoria = await _categoria(db_session, grupo_nome="Transportes", nome="Fuel Type")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=3, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    primeira = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 1), valor=Decimal("-60.00"), descricao="GALP AREAS 444441",
    )
    segunda = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 5), valor=Decimal("-55.00"), descricao="GALP AREAS 444442",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, primeira.id)
    await linha_extrato_repo.marcar_revisao_manual(db_session, segunda.id)
    await db_session.commit()

    await resolver_como_despesa(
        db_session, linha_id=primeira.id, categoria_id=categoria.id, leitura_odometro=120000
    )

    resultado = await db_session.execute(select(MovimentoLinha))
    linhas_criadas = resultado.scalars().all()
    assert len(linhas_criadas) == 1
    assert linhas_criadas[0].leitura_odometro == 120000


@pytest.mark.asyncio
async def test_verificar_movimentos_sem_extrato_alerta_saidas_e_entradas_e_nao_duplica(db_session):
    categoria = await _categoria(db_session)
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("45.67"),
        data=date(2026, 7, 1),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("45.67"), categoria_id=categoria.id)],
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="entrada",
        valor=Decimal("1500.00"),
        data=date(2026, 7, 1),
        origem="regra",
        linhas=[LinhaNova(valor=Decimal("1500.00"))],
    )
    # Achado de 2026-08-20: faltava esta origem/tipo em _INVERSOS -- uma despesa recorrente
    # (Recorrente tipo="saida") gerada como "regra" não tinha nenhum alerta equivalente ao de
    # "documento" acima, apesar de ter a mesma exposição (nunca reconciliada com o extrato).
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("12.99"),
        data=date(2026, 7, 5),
        origem="regra",
        linhas=[LinhaNova(valor=Decimal("12.99"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    chaves = await verificar_movimentos_sem_extrato(
        db_session, referencia=date(2026, 7, 15), prazo_dias=10
    )
    assert len(chaves) == 3

    assert (
        await verificar_movimentos_sem_extrato(db_session, referencia=date(2026, 7, 16), prazo_dias=10)
        == []
    )


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_liga_linha_de_credito_e_de_conta_a_ordem(db_session):
    # Achado real: o mesmo pagamento de prestação aparece como DUAS linhas de extrato pendentes
    # distintas - "AMORTIZACAO DE CAPITAL" na conta de divida, e "AMORTIZACAO DE CAPITAL -
    # <contrato>" na conta a ordem que debitou o pagamento - mesma data, mesmo valor absoluto.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=16, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    linha_credito_lida = await linha_extrato_repo.obter_por_id(db_session, linha_credito.id)
    assert linha_a_ordem_lida.estado == "conciliado"
    assert linha_credito_lida.estado == "conciliado"

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert len(movimentos) == 1
    movimento = movimentos[0]
    assert movimento.valor == Decimal("457.33")
    assert movimento.conta_id == conta_a_ordem.id
    assert movimento.conta_destino_id == conta_credito.id
    assert movimento.linha_extrato_id == linha_a_ordem.id
    assert movimento.linha_extrato_destino_id == linha_credito.id
    assert movimento.linhas[0].categoria_id is None  # ainda por categorizar


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_atribui_categoria_pagamento_de_credito_automaticamente(db_session):
    # Pedido do utilizador: o destino já diz tudo (uma conta tipo="divida") — não faz sentido
    # obrigar a escolher categoria manualmente para cada amortização de crédito. Ver categorias_
    # iniciais.py, grupo "Encargos financeiros".
    categoria_pagamento = await _categoria(
        db_session, grupo_nome="Encargos financeiros", nome="Pagamento de crédito"
    )
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=17, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert len(movimentos) == 1
    assert movimentos[0].linhas[0].categoria_id == categoria_pagamento.id
    assert movimentos[0].linha_extrato_id == linha_a_ordem.id


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_liga_linhas_ja_em_revisao_manual(db_session):
    # Achado em produção: uma importação histórica em bloco (antes desta função existir) já
    # passou as duas linhas pelo caminho normal de reconciliação sem candidato — ficaram em
    # "revisao_manual", não "pendente". Sem considerar também este estado, o emparelhamento
    # nunca aconteceria para o histórico já importado, só para extratos futuros.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=24, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_a_ordem.id)
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_credito.id)
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    linha_credito_lida = await linha_extrato_repo.obter_por_id(db_session, linha_credito.id)
    assert linha_a_ordem_lida.estado == "conciliado"
    assert linha_credito_lida.estado == "conciliado"

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert len(movimentos) == 1


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_nao_liga_quando_valor_nao_bate(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=17, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-999.00"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    linha_credito_lida = await linha_extrato_repo.obter_por_id(db_session, linha_credito.id)
    assert linha_a_ordem_lida.estado == "pendente"
    assert linha_credito_lida.estado == "pendente"
    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert movimentos == []


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_com_duas_contas_de_credito_emparelha_cada_uma_corretamente(
    db_session,
):
    # Duas contas de credito distintas, amortizacoes no MESMO dia mas valores diferentes - cada
    # uma tem de emparelhar com a linha certa da conta a ordem, nao misturar.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    credito_habitacao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    credito_pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Pessoal"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=18, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem_habitacao = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_a_ordem_pessoal = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-185.37"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-830-003",
    )
    linha_credito_habitacao = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_habitacao.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    linha_credito_pessoal = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_pessoal.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-185.37"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    for linha in (
        linha_a_ordem_habitacao,
        linha_a_ordem_pessoal,
        linha_credito_habitacao,
        linha_credito_pessoal,
    ):
        atualizada = await linha_extrato_repo.obter_por_id(db_session, linha.id)
        assert atualizada.estado == "conciliado"

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert len(movimentos) == 2
    por_destino = {m.conta_destino_id: m for m in movimentos}
    assert por_destino[credito_habitacao.id].valor == Decimal("457.33")
    assert por_destino[credito_habitacao.id].linha_extrato_id == linha_a_ordem_habitacao.id
    assert por_destino[credito_pessoal.id].valor == Decimal("185.37")
    assert por_destino[credito_pessoal.id].linha_extrato_id == linha_a_ordem_pessoal.id


@pytest.mark.asyncio
async def test_conciliar_amortizacoes_duas_contas_de_credito_colidindo_no_mesmo_valor_e_data_so_empareiha_uma(
    db_session,
):
    # A colisão real que o .remove() em conciliar_amortizacoes_de_credito protege: DUAS contas de
    # crédito com amortização no MESMO dia e MESMO valor (coincidência rara mas possível), e só
    # UMA linha candidata do lado da conta à ordem para essa combinação data+valor. Sem o
    # .remove(), as duas contas de crédito reivindicariam a MESMA linha da conta à ordem, criando
    # duas transferências a apontar para a mesma linha_extrato_id — dinheiro duplicado no
    # histórico. O resultado correto: só uma delas empareiha; a outra fica pendente (nunca
    # adivinha, mesmo princípio de conciliar_uma_linha).
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    credito_habitacao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    credito_pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Pessoal"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=23, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-300.00"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito_habitacao = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_habitacao.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-300.00"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    linha_credito_pessoal = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_pessoal.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-300.00"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    assert linha_a_ordem_lida.estado == "conciliado"  # usada exatamente uma vez

    estados_credito = {
        linha_credito_habitacao.id: (
            await linha_extrato_repo.obter_por_id(db_session, linha_credito_habitacao.id)
        ).estado,
        linha_credito_pessoal.id: (
            await linha_extrato_repo.obter_por_id(db_session, linha_credito_pessoal.id)
        ).estado,
    }
    # exatamente uma das duas contas de crédito empareihou; a outra fica pendente
    assert sorted(estados_credito.values()) == ["conciliado", "pendente"]

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="transferencia"
    )
    assert len(movimentos) == 1  # nunca duas transferências a apontar para a mesma linha


@pytest.mark.asyncio
async def test_reconciliar_linhas_pendentes_emparelha_amortizacoes_antes_do_loop_normal(db_session):
    # Integracao: reconciliar_linhas_pendentes chama conciliar_amortizacoes_de_credito PRIMEIRO -
    # depois de emparelhadas, as duas linhas nao devem ser tratadas pelo loop normal (que as
    # mandaria para revisao manual, por nao terem candidato de movimento unico).
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=19, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await reconciliar_linhas_pendentes(db_session)

    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    linha_credito_lida = await linha_extrato_repo.obter_por_id(db_session, linha_credito.id)
    assert linha_a_ordem_lida.estado == "conciliado"
    assert linha_credito_lida.estado == "conciliado"
    pendentes_revisao = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert linha_a_ordem.id not in [p.id for p in pendentes_revisao]
    assert linha_credito.id not in [p.id for p in pendentes_revisao]


@pytest.mark.asyncio
async def test_categorizar_transferencia_aplica_a_todas_as_transferencias_da_mesma_conta_destino(
    db_session,
):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    cat = await _categoria(db_session, nome="Amortizacao Credito Habitacao")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=20, nivel_extracao=0, dados_extraidos={}
    )

    async def _linha_e_movimento_transferencia(mes: int, valor: str):
        linha_ordem = await linha_extrato_repo.criar_linha(
            db_session,
            conta_id=conta_a_ordem.id,
            documento_id=documento.id,
            data=date(2026, mes, 25),
            valor=Decimal(valor),
            descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
        )
        linha_cred = await linha_extrato_repo.criar_linha(
            db_session,
            conta_id=conta_credito.id,
            documento_id=documento.id,
            data=date(2026, mes, 25),
            valor=Decimal(valor),
            descricao="AMORTIZACAO DE CAPITAL",
        )
        return linha_ordem, linha_cred

    await _linha_e_movimento_transferencia(5, "-455.00")
    await _linha_e_movimento_transferencia(6, "-456.00")
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    movimentos = await movimento_repo.listar_transferencias_sem_categoria(db_session)
    assert len(movimentos) == 2

    assert (
        await categorizar_transferencia(db_session, movimento_id=movimentos[0].id, categoria_id=cat.id)
        is True
    )

    ainda_por_categorizar = await movimento_repo.listar_transferencias_sem_categoria(db_session)
    assert ainda_por_categorizar == []

    todas = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 1, 1), fim=date(2026, 12, 31), tipo="transferencia"
    )
    assert len(todas) == 2
    for movimento in todas:
        assert movimento.linhas[0].categoria_id == cat.id


@pytest.mark.asyncio
async def test_categorizar_transferencia_nao_atravessa_contas_de_destino_diferentes(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    credito_habitacao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    credito_pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Pessoal"
    )
    cat_habitacao = await _categoria(db_session, nome="Amortizacao Credito Habitacao")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=21, nivel_extracao=0, dados_extraidos={}
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_habitacao.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-185.37"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-830-003",
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_pessoal.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-185.37"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()

    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    movimentos = await movimento_repo.listar_transferencias_sem_categoria(db_session)
    movimento_habitacao = next(m for m in movimentos if m.conta_destino_id == credito_habitacao.id)

    assert (
        await categorizar_transferencia(
            db_session, movimento_id=movimento_habitacao.id, categoria_id=cat_habitacao.id
        )
        is True
    )

    ainda_por_categorizar = await movimento_repo.listar_transferencias_sem_categoria(db_session)
    assert len(ainda_por_categorizar) == 1
    assert ainda_por_categorizar[0].conta_destino_id == credito_pessoal.id


@pytest.mark.asyncio
async def test_categorizar_transferencia_recusa_movimento_ja_categorizado(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    cat = await _categoria(db_session, nome="Amortizacao Credito Habitacao")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=22, nivel_extracao=0, dados_extraidos={}
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()
    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    movimento = (await movimento_repo.listar_transferencias_sem_categoria(db_session))[0]
    assert await categorizar_transferencia(db_session, movimento_id=movimento.id, categoria_id=cat.id) is True

    outra_categoria = await _categoria(db_session, grupo_nome="Outro Grupo", nome="Outra Categoria")
    assert (
        await categorizar_transferencia(
            db_session, movimento_id=movimento.id, categoria_id=outra_categoria.id
        )
        is False
    )


@pytest.mark.asyncio
async def test_desfazer_movimento_apaga_e_devolve_linha_a_revisao_manual(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    cat = await _categoria(db_session, nome="Supermercado")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=25, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 6),
        valor=Decimal("-30.00"),
        descricao="COMPRA CONTINENTE",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()
    assert await resolver_como_despesa(db_session, linha_id=linha.id, categoria_id=cat.id) is True

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )
    assert len(movimentos) == 1
    movimento_id = movimentos[0].id

    assert await desfazer_movimento(db_session, movimento_id=movimento_id) is True

    assert await movimento_repo.obter_por_id(db_session, movimento_id) is None
    linha_lida = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_lida.estado == "revisao_manual"


@pytest.mark.asyncio
async def test_desfazer_transferencia_devolve_as_duas_linhas_a_revisao_manual(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta a Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Credito Habitacao"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=26, nivel_extracao=0, dados_extraidos={}
    )
    linha_a_ordem = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_a_ordem.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL - 0000000-165-008",
    )
    linha_credito = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta_credito.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-457.33"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await db_session.commit()
    await conciliar_amortizacoes_de_credito(db_session)
    await db_session.commit()

    movimento = (await movimento_repo.listar_transferencias_sem_categoria(db_session))[0]

    assert await desfazer_movimento(db_session, movimento_id=movimento.id) is True

    assert await movimento_repo.obter_por_id(db_session, movimento.id) is None
    linha_a_ordem_lida = await linha_extrato_repo.obter_por_id(db_session, linha_a_ordem.id)
    linha_credito_lida = await linha_extrato_repo.obter_por_id(db_session, linha_credito.id)
    assert linha_a_ordem_lida.estado == "revisao_manual"
    assert linha_credito_lida.estado == "revisao_manual"


@pytest.mark.asyncio
async def test_desfazer_movimento_sem_linha_extrato_so_apaga(db_session):
    # Um movimento de origem="regra"/"manual" (ex. rendimento recorrente, ou uma despesa
    # registada manualmente via Telegram) nunca teve uma linha_extrato a reconciliar — desfazer
    # tem só de o apagar, sem rebentar a tentar repor uma linha que não existe.
    categoria = await _categoria(db_session, grupo_nome="Rendimentos", nome="Salário", tipo="receita")
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="entrada",
        valor=Decimal("1500.00"),
        data=date(2026, 7, 1),
        origem="regra",
        linhas=[LinhaNova(valor=Decimal("1500.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    assert await desfazer_movimento(db_session, movimento_id=movimento.id) is True
    assert await movimento_repo.obter_por_id(db_session, movimento.id) is None


@pytest.mark.asyncio
async def test_desfazer_movimento_ficheiro_limpa_categoria_e_mantem_movimento(db_session):
    # Um movimento de origem="ficheiro" (export do BPI Net) não tem linha_extrato_id:
    # desfazer não o deve apagar da base de dados, mas sim limpar categoria_id das suas linhas
    # para que volte a aparecer na lista de movimentos por categorizar.
    categoria = await _categoria(db_session, grupo_nome="Alimentação", nome="Restaurantes", tipo="despesa")
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("25.50"),
        data=date(2026, 8, 12),
        origem="ficheiro",
        descricao="RESTAURANTE CENTRAL",
        linhas=[LinhaNova(valor=Decimal("25.50"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    assert await desfazer_movimento(db_session, movimento_id=movimento.id) is True
    mov_atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert mov_atualizado is not None
    assert mov_atualizado.descricao == "RESTAURANTE CENTRAL"
    assert mov_atualizado.linhas[0].categoria_id is None


@pytest.mark.asyncio
async def test_desfazer_movimento_manual_limpa_categoria_e_mantem_movimento(db_session):
    # Um movimento de origem="manual" (registo manual ou telegram) sem linha_extrato_id:
    # desfazer limpa a categoria para permitir reclassificação em /movimentos sem perder o registo.
    categoria = await _categoria(db_session, grupo_nome="Alimentação", nome="Supermercado", tipo="despesa")
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("15.00"),
        data=date(2026, 8, 14),
        origem="manual",
        descricao="Café e lanche",
        linhas=[LinhaNova(valor=Decimal("15.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    assert await desfazer_movimento(db_session, movimento_id=movimento.id) is True
    mov_atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert mov_atualizado is not None
    assert mov_atualizado.linhas[0].categoria_id is None


@pytest.mark.asyncio
async def test_desfazer_movimento_inexistente_devolve_false(db_session):
    assert await desfazer_movimento(db_session, movimento_id=uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_transferencia_manual_nao_arrasta_amortizacoes_de_outro_credito(db_session):
    # parse_banco_bpi devolve "AMORTIZACAO DE CAPITAL" idêntico para créditos diferentes, e ambos
    # saem da mesma conta à ordem — a antiga restrição por conta de origem não distinguia nada.
    # Propagar aqui atribuía pagamentos ao crédito errado.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    habitacao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", categoria_divida="habitacao",
    )
    pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Crédito Pessoal", categoria_divida="pessoal",
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=5, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    linhas = []
    for dia, valor in ((3, Decimal("-450.00")), (10, Decimal("-120.00"))):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=ordem.id, documento_id=documento.id,
            data=date(2026, 8, dia), valor=valor, descricao="AMORTIZACAO DE CAPITAL",
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
        linhas.append(linha)
    await db_session.commit()

    await resolver_como_transferencia(
        db_session, linha_id=linhas[0].id, conta_relacionada_id=habitacao.id
    )
    # A segunda continua pendente e pode ir para o OUTRO crédito.
    pendentes = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert [linha.id for linha in pendentes] == [linhas[1].id]

    await resolver_como_transferencia(
        db_session, linha_id=linhas[1].id, conta_relacionada_id=pessoal.id
    )

    resultado = await db_session.execute(select(Movimento).order_by(Movimento.data))
    destinos = [movimento.conta_destino_id for movimento in resultado.scalars().all()]
    assert destinos == [habitacao.id, pessoal.id]
