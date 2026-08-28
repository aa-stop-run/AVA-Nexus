from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import (
    categoria_repo,
    conta_repo,
    documento_repo,
    fornecedor_repo,
    linha_extrato_repo,
    movimento_repo,
    titular_repo,
)
from ava.repositories.movimento_repo import LinhaNova, SomaDasLinhasNaoBate, ValorNaoPositivo
from tests.fabricas import criar_conta as fabrica_criar_conta
from tests.fabricas import criar_movimento as fabrica_criar_movimento
from tests.fabricas import criar_titular_e_conta, criar_transferencia


async def _categoria(db_session, grupo_nome="Alimentação", nome="Supermercado", tipo="despesa"):
    grupo = await categoria_repo.criar_grupo(db_session, nome=grupo_nome)
    natureza = "extraordinario" if tipo == "receita" else "variavel"
    return await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=nome, tipo=tipo, natureza=natureza
    )


@pytest.mark.asyncio
async def test_criar_movimento_simples_guarda_uma_linha(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("63.18"),
        data=date(2026, 7, 23),
        origem="extrato",
        descricao="PINGO DOCE 4127",
        linhas=[LinhaNova(valor=Decimal("63.18"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert lido.valor == Decimal("63.18")
    assert len(lido.linhas) == 1
    assert lido.linhas[0].categoria_id == categoria.id


@pytest.mark.asyncio
async def test_criar_movimento_dividido_guarda_as_duas_linhas(db_session):
    combustivel = await _categoria(db_session, "Transportes", "Fuel Type")
    tabaco = await _categoria(db_session, "Pessoal", "Tabaco")
    await db_session.commit()

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("40.00"),
        data=date(2026, 7, 19),
        origem="extrato",
        descricao="GALP ENERGIA",
        linhas=[
            LinhaNova(valor=Decimal("30.00"), categoria_id=combustivel.id),
            LinhaNova(valor=Decimal("10.00"), categoria_id=tabaco.id),
        ],
    )
    await db_session.commit()

    lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert sorted(linha.valor for linha in lido.linhas) == [Decimal("10.00"), Decimal("30.00")]


@pytest.mark.asyncio
async def test_soma_das_linhas_diferente_do_total_e_rejeitada(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()

    with pytest.raises(SomaDasLinhasNaoBate):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal("40.00"),
            data=date(2026, 7, 19),
            origem="manual",
            linhas=[LinhaNova(valor=Decimal("30.00"), categoria_id=categoria.id)],
        )


@pytest.mark.asyncio
async def test_movimento_sem_linhas_e_rejeitado(db_session):
    with pytest.raises(SomaDasLinhasNaoBate):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal("10.00"),
            data=date(2026, 7, 19),
            origem="manual",
            linhas=[],
        )


# --- Achado Importante (revisão final Fase A): movimento.valor > 0 nunca era imposto ---
#
# A regra global do projeto ("movimento.valor é sempre positivo; a direção vem de tipo") só era
# protegida indiretamente por 4 dos 5 produtores (faturas, Telegram via Field(gt=0), reconciliação
# via abs()) — nada em criar_movimento impedia um par (-450, [-450]) de satisfazer o checksum da
# soma perfeitamente. O quinto produtor (/rendimentos-recorrentes/novo) não tinha proteção nenhuma.


@pytest.mark.asyncio
async def test_valor_negativo_e_rejeitado_mesmo_com_soma_a_bater(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()

    # (-450, [-450]) bate no checksum da soma perfeitamente — só a verificação de sinal o rejeita.
    with pytest.raises(ValorNaoPositivo):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal("-450.00"),
            data=date(2026, 7, 19),
            origem="manual",
            linhas=[LinhaNova(valor=Decimal("-450.00"), categoria_id=categoria.id)],
        )


@pytest.mark.asyncio
async def test_valor_zero_e_rejeitado(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()

    with pytest.raises(ValorNaoPositivo):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal("0.00"),
            data=date(2026, 7, 19),
            origem="manual",
            linhas=[LinhaNova(valor=Decimal("0.00"), categoria_id=categoria.id)],
        )


@pytest.mark.asyncio
async def test_valor_negativo_nao_persiste_nada_na_base(db_session):
    # A validação de sinal acontece ANTES de qualquer session.add — confirma que nenhum
    # Movimento nem MovimentoLinha ficou gravado depois da exceção.
    categoria = await _categoria(db_session)
    await db_session.commit()

    with pytest.raises(ValorNaoPositivo):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal("-10.00"),
            data=date(2026, 7, 19),
            origem="manual",
            linhas=[LinhaNova(valor=Decimal("-10.00"), categoria_id=categoria.id)],
        )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert movimentos == []


@pytest.mark.asyncio
async def test_linha_guarda_o_contador(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Habitação")
    eletricidade = await categoria_repo.criar_categoria(
        db_session,
        grupo_id=grupo.id,
        nome="Eletricidade",
        tipo="despesa",
        natureza="variavel",
        unidade_contador="kWh",
    )
    await db_session.commit()

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("95.40"),
        data=date(2026, 7, 26),
        origem="documento",
        linhas=[
            LinhaNova(
                valor=Decimal("95.40"),
                categoria_id=eletricidade.id,
                quantidade=Decimal("312.000"),
                unidade="kWh",
            )
        ],
    )
    await db_session.commit()

    lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert lido.linhas[0].quantidade == Decimal("312.000")
    assert lido.linhas[0].unidade == "kWh"


@pytest.mark.asyncio
async def test_transferencia_tem_linha_sem_categoria_e_conta_destino(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    divida = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="divida", nome="Habitação"
    )
    await db_session.commit()

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("412.00"),
        data=date(2026, 7, 24),
        origem="extrato",
        descricao="PRESTACAO CREDITO HABITACAO",
        conta_id=ordem.id,
        conta_destino_id=divida.id,
        linhas=[LinhaNova(valor=Decimal("412.00"))],
    )
    await db_session.commit()

    lido = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert lido.conta_destino_id == divida.id
    assert lido.linhas[0].categoria_id is None


@pytest.mark.asyncio
async def test_listar_por_periodo_filtra_data_e_tipo(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()
    for dia, tipo in ((5, "saida"), (15, "entrada"), (25, "saida")):
        await movimento_repo.criar_movimento(
            db_session,
            tipo=tipo,
            valor=Decimal("10.00"),
            data=date(2026, 7, dia),
            origem="manual",
            linhas=[LinhaNova(valor=Decimal("10.00"), categoria_id=categoria.id)],
        )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("99.00"),
        data=date(2026, 8, 2),
        origem="manual",
        linhas=[LinhaNova(valor=Decimal("99.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    julho = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(julho) == 3

    saidas = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )
    assert len(saidas) == 2


@pytest.mark.asyncio
async def test_candidatos_para_conciliar_exclui_os_ja_ligados(db_session):
    categoria = await _categoria(db_session)
    await db_session.commit()

    livre = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("45.67"),
        data=date(2026, 7, 3),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("45.67"), categoria_id=categoria.id)],
    )
    fora_da_janela = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("45.67"),
        data=date(2026, 6, 1),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("45.67"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    candidatos = await movimento_repo.listar_candidatos_para_conciliar(
        db_session, tipo="saida", valor=Decimal("45.67"), data=date(2026, 7, 5), janela_dias=5
    )
    assert [c.id for c in candidatos] == [livre.id]
    assert fora_da_janela.id not in [c.id for c in candidatos]


@pytest.mark.asyncio
async def test_listar_sem_linha_extrato_filtra_tipo_origem_data_e_ligacao(db_session):
    """Os quatro filtros da consulta, cada um provado por um caso que deve ficar de fora."""
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.commit()

    limite_data = date(2026, 7, 15)

    elegivel = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("50.00"),
        data=date(2026, 7, 10),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("50.00"))],
    )

    # exclusão 1: tipo diferente
    tipo_diferente = await movimento_repo.criar_movimento(
        db_session,
        tipo="entrada",
        valor=Decimal("50.00"),
        data=date(2026, 7, 10),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("50.00"))],
    )

    # exclusão 2: já ligado a uma linha de extrato
    linha_extrato = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 9),
        valor=Decimal("-30.00"),
    )
    ja_ligado = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("30.00"),
        data=date(2026, 7, 10),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("30.00"))],
        linha_extrato_id=linha_extrato.id,
    )

    # exclusão 3: data posterior ao limite
    data_posterior = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("20.00"),
        data=date(2026, 7, 20),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("20.00"))],
    )

    # exclusão 4: origem diferente
    origem_diferente = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("15.00"),
        data=date(2026, 7, 10),
        origem="telegram",
        linhas=[LinhaNova(valor=Decimal("15.00"))],
    )

    await db_session.commit()

    resultado = await movimento_repo.listar_sem_linha_extrato(
        db_session, tipo="saida", limite_data=limite_data, origem="documento"
    )

    ids = {m.id for m in resultado}
    assert ids == {elegivel.id}
    assert tipo_diferente.id not in ids
    assert ja_ligado.id not in ids
    assert data_posterior.id not in ids
    assert origem_diferente.id not in ids


@pytest.mark.asyncio
async def test_historico_valores_registo_rapido_filtra_titular_tipo_origem_e_respeita_limite(db_session):
    """Filtra por titular e tipo, aceita origem "manual" e "telegram", ordena por data desc.

    "telegram" continua incluída de propósito: era a origem enquanto a captura rápida foi feita
    pelo bot (removido), e esse histórico continua a ser a base do teto de magnitude.

    Os três casos de exclusão têm a data mais recente de todos — se algum filtro estiver trocado,
    esse movimento aparece em primeiro lugar (ordenação desc) e desloca um valor correto da lista.
    """
    titular_a = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    titular_b = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async def _movimento(*, titular_id, tipo, origem, dia, valor):
        return await movimento_repo.criar_movimento(
            db_session,
            tipo=tipo,
            valor=valor,
            data=date(2026, 7, dia),
            origem=origem,
            titular_id=titular_id,
            linhas=[LinhaNova(valor=valor)],
        )

    await _movimento(titular_id=titular_a.id, tipo="saida", origem="telegram", dia=1, valor=Decimal("10.00"))
    await _movimento(titular_id=titular_a.id, tipo="saida", origem="telegram", dia=5, valor=Decimal("20.00"))
    await _movimento(titular_id=titular_a.id, tipo="saida", origem="telegram", dia=10, valor=Decimal("30.00"))
    await _movimento(titular_id=titular_a.id, tipo="saida", origem="telegram", dia=15, valor=Decimal("40.00"))

    # exclusão 1: outro titular, mais recente que todos os corretos
    await _movimento(titular_id=titular_b.id, tipo="saida", origem="telegram", dia=20, valor=Decimal("999.00"))
    # exclusão 2: tipo diferente, mais recente que todos os corretos
    await _movimento(titular_id=titular_a.id, tipo="entrada", origem="telegram", dia=21, valor=Decimal("888.00"))
    # exclusão 3: origem diferente, mais recente que todos os corretos
    await _movimento(titular_id=titular_a.id, tipo="saida", origem="extrato", dia=22, valor=Decimal("777.00"))
    # origem "manual" (a atual do registo rápido) conta tal como a legada "telegram"
    await _movimento(titular_id=titular_a.id, tipo="saida", origem="manual", dia=18, valor=Decimal("50.00"))

    await db_session.commit()

    historico = await movimento_repo.historico_valores_registo_rapido(
        db_session, titular_id=titular_a.id, tipo="saida", limite=3
    )

    assert historico == [Decimal("50.00"), Decimal("40.00"), Decimal("30.00")]


@pytest.mark.asyncio
async def test_historico_valores_fornecedor_ignora_movimentos_de_entrada(db_session):
    # Contra-exemplo do filtro tipo == "saida": os testes existentes de validar_fatura só criam
    # movimentos de saída para o histórico, portanto nunca provaram que o filtro está realmente
    # aplicado — se alguém o removesse de historico_valores_fornecedor, nada falharia. Aqui o
    # mesmo fornecedor tem uma saída e uma entrada; sem o filtro, o valor da entrada (um
    # rendimento, por exemplo um reembolso do próprio fornecedor) contaminaria o teto de
    # magnitude das faturas com um valor que não é despesa.
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("50.00"),
        data=date(2026, 7, 1),
        origem="documento",
        fornecedor_id=fornecedor.id,
        linhas=[LinhaNova(valor=Decimal("50.00"))],
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="entrada",
        valor=Decimal("999.00"),
        data=date(2026, 7, 2),
        origem="documento",
        fornecedor_id=fornecedor.id,
        linhas=[LinhaNova(valor=Decimal("999.00"))],
    )
    await db_session.commit()

    historico = await movimento_repo.historico_valores_fornecedor(db_session, fornecedor.id)

    assert historico == [Decimal("50.00")]
    assert Decimal("999.00") not in historico


@pytest.mark.asyncio
async def test_historico_pagamentos_fornecedor_devolve_data_e_valor_mais_recente_primeiro(db_session):
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    for dia, valor in ((1, "30.00"), (2, "40.00"), (3, "50.00")):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal(valor), data=date(2026, 7, dia),
            origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal(valor))],
        )
    await db_session.commit()

    historico = await movimento_repo.historico_pagamentos_fornecedor(db_session, fornecedor.id)

    assert historico == [
        (date(2026, 7, 3), Decimal("50.00")),
        (date(2026, 7, 2), Decimal("40.00")),
        (date(2026, 7, 1), Decimal("30.00")),
    ]


@pytest.mark.asyncio
async def test_historico_pagamentos_fornecedor_ignora_movimentos_de_entrada(db_session):
    # Mesmo cuidado do teste equivalente de historico_valores_fornecedor: sem o filtro tipo ==
    # "saida", um reembolso do próprio fornecedor apareceria misturado com as despesas reais.
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal("50.00"))],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("999.00"), data=date(2026, 7, 2),
        origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal("999.00"))],
    )
    await db_session.commit()

    historico = await movimento_repo.historico_pagamentos_fornecedor(db_session, fornecedor.id)

    assert historico == [(date(2026, 7, 1), Decimal("50.00"))]


@pytest.mark.asyncio
async def test_historico_pagamentos_fornecedor_respeita_o_limite(db_session):
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    for dia in range(1, 6):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal("10.00"), data=date(2026, 7, dia),
            origem="documento", fornecedor_id=fornecedor.id, linhas=[LinhaNova(valor=Decimal("10.00"))],
        )
    await db_session.commit()

    historico = await movimento_repo.historico_pagamentos_fornecedor(db_session, fornecedor.id, limite=2)

    assert len(historico) == 2
    assert historico[0] == (date(2026, 7, 5), Decimal("10.00"))


@pytest.mark.asyncio
async def test_historico_valores_categoria_devolve_valores_mais_recente_primeiro(db_session):
    categoria = await _categoria(db_session, nome="Consultas")

    for dia, valor in ((1, "40.00"), (2, "50.00"), (3, "60.00")):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal(valor), data=date(2026, 7, dia),
            origem="manual", linhas=[LinhaNova(valor=Decimal(valor), categoria_id=categoria.id)],
        )
    await db_session.commit()

    historico = await movimento_repo.historico_valores_categoria(db_session, categoria.id)

    assert historico == [Decimal("60.00"), Decimal("50.00"), Decimal("40.00")]


@pytest.mark.asyncio
async def test_historico_valores_categoria_ignora_outras_categorias(db_session):
    consultas = await _categoria(db_session, nome="Consultas")
    supermercado = await _categoria(db_session, grupo_nome="Alimentação 2", nome="Supermercado 2")

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="manual", linhas=[LinhaNova(valor=Decimal("50.00"), categoria_id=consultas.id)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("999.00"), data=date(2026, 7, 2),
        origem="manual", linhas=[LinhaNova(valor=Decimal("999.00"), categoria_id=supermercado.id)],
    )
    await db_session.commit()

    historico = await movimento_repo.historico_valores_categoria(db_session, consultas.id)

    assert historico == [Decimal("50.00")]


@pytest.mark.asyncio
async def test_historico_valores_categoria_respeita_o_limite(db_session):
    categoria = await _categoria(db_session, nome="Consultas")

    for dia in range(1, 6):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal("10.00"), data=date(2026, 7, dia),
            origem="manual", linhas=[LinhaNova(valor=Decimal("10.00"), categoria_id=categoria.id)],
        )
    await db_session.commit()

    historico = await movimento_repo.historico_valores_categoria(db_session, categoria.id, limite=2)

    assert len(historico) == 2


@pytest.mark.asyncio
async def test_listar_por_categoria_devolve_despesas_do_periodo_mais_recente_primeiro(db_session):
    categoria = await _categoria(db_session, nome="Consultas")

    for dia, valor in ((1, "40.00"), (2, "50.00"), (3, "60.00")):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal(valor), data=date(2026, 7, dia),
            origem="manual", descricao=f"Consulta dia {dia}",
            linhas=[LinhaNova(valor=Decimal(valor), categoria_id=categoria.id)],
        )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=categoria.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
    )

    assert [d.valor for d in despesas] == [Decimal("60.00"), Decimal("50.00"), Decimal("40.00")]
    assert despesas[0].descricao == "Consulta dia 3"
    assert despesas[0].data == date(2026, 7, 3)


@pytest.mark.asyncio
async def test_listar_por_categoria_ignora_categoria_diferente(db_session):
    consultas = await _categoria(db_session, nome="Consultas")
    supermercado = await _categoria(db_session, grupo_nome="Alimentação 2", nome="Supermercado 2")

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="manual", linhas=[LinhaNova(valor=Decimal("50.00"), categoria_id=consultas.id)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("999.00"), data=date(2026, 7, 2),
        origem="manual", linhas=[LinhaNova(valor=Decimal("999.00"), categoria_id=supermercado.id)],
    )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=consultas.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
    )

    assert [d.valor for d in despesas] == [Decimal("50.00")]


@pytest.mark.asyncio
async def test_listar_por_categoria_ignora_fora_do_periodo(db_session):
    categoria = await _categoria(db_session, nome="Consultas")

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 6, 30),
        origem="manual", linhas=[LinhaNova(valor=Decimal("50.00"), categoria_id=categoria.id)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("60.00"), data=date(2026, 8, 1),
        origem="manual", linhas=[LinhaNova(valor=Decimal("60.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=categoria.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
    )

    assert despesas == []


@pytest.mark.asyncio
async def test_listar_por_categoria_respeita_titular_id(db_session):
    categoria = await _categoria(db_session, nome="Consultas")
    titular_a = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    titular_b = await titular_repo.criar_titular(db_session, nome="Bruno", tipo="proprio")
    await db_session.flush()

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="manual", titular_id=titular_a.id,
        linhas=[LinhaNova(valor=Decimal("50.00"), categoria_id=categoria.id)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("999.00"), data=date(2026, 7, 2),
        origem="manual", titular_id=titular_b.id,
        linhas=[LinhaNova(valor=Decimal("999.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=categoria.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
        titular_id=titular_a.id,
    )

    assert [d.valor for d in despesas] == [Decimal("50.00")]


@pytest.mark.asyncio
async def test_listar_por_categoria_inclui_transferencia_categorizada(db_session):
    # Mesmo filtro de tipo que totais_por_categoria usa para despesas -- uma amortização
    # categorizada conta para o total mostrado no dashboard, por isso tem de aparecer também
    # nesta lista, senão a soma das linhas visíveis não bate com o total do cabeçalho.
    categoria = await _categoria(db_session, nome="Dívida")
    titular, conta = await criar_titular_e_conta(db_session)
    destino = await fabrica_criar_conta(db_session, titular=titular, tipo="cartao_credito", nome="Cartão")
    await db_session.commit()

    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=destino, valor="75.00",
        data=date(2026, 7, 10), categoria_id=categoria.id,
    )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=categoria.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
    )

    assert [d.valor for d in despesas] == [Decimal("75.00")]


@pytest.mark.asyncio
async def test_listar_por_categoria_usa_valor_da_linha_num_movimento_dividido(db_session):
    supermercado = await _categoria(db_session, nome="Supermercado")
    farmacia = await _categoria(db_session, grupo_nome="Saúde", nome="Farmácia")

    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("100.00"), data=date(2026, 7, 5),
        origem="manual", descricao="CONTINENTE",
        linhas=[
            LinhaNova(valor=Decimal("60.00"), categoria_id=supermercado.id),
            LinhaNova(valor=Decimal("40.00"), categoria_id=farmacia.id),
        ],
    )
    await db_session.commit()

    despesas = await movimento_repo.listar_por_categoria(
        db_session, categoria_id=supermercado.id, inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
    )

    assert [d.valor for d in despesas] == [Decimal("60.00")]
    assert despesas[0].descricao == "CONTINENTE"


@pytest.mark.asyncio
async def test_ligar_a_linha_extrato_grava_e_remove_o_movimento_dos_pendentes(db_session):
    """Grava a ligação e, sobretudo, tira o movimento de listar_candidatos_para_conciliar e de
    listar_sem_linha_extrato — é nisto que a reconciliação assenta para não casar duas vezes."""
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=10, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.commit()

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("22.50"),
        data=date(2026, 7, 12),
        origem="documento",
        linhas=[LinhaNova(valor=Decimal("22.50"))],
    )
    await db_session.commit()

    # antes de ligar: aparece como candidato a conciliar e como pendente sem linha de extrato
    candidatos_antes = await movimento_repo.listar_candidatos_para_conciliar(
        db_session, tipo="saida", valor=Decimal("22.50"), data=date(2026, 7, 12), janela_dias=2
    )
    assert movimento.id in [m.id for m in candidatos_antes]

    pendentes_antes = await movimento_repo.listar_sem_linha_extrato(
        db_session, tipo="saida", limite_data=date(2026, 7, 31), origem="documento"
    )
    assert movimento.id in [m.id for m in pendentes_antes]

    linha_extrato = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 12),
        valor=Decimal("-22.50"),
    )
    await db_session.commit()

    await movimento_repo.ligar_a_linha_extrato(db_session, movimento.id, linha_extrato.id)
    await db_session.commit()

    ligado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert ligado.linha_extrato_id == linha_extrato.id

    candidatos_depois = await movimento_repo.listar_candidatos_para_conciliar(
        db_session, tipo="saida", valor=Decimal("22.50"), data=date(2026, 7, 12), janela_dias=2
    )
    assert movimento.id not in [m.id for m in candidatos_depois]

    pendentes_depois = await movimento_repo.listar_sem_linha_extrato(
        db_session, tipo="saida", limite_data=date(2026, 7, 31), origem="documento"
    )
    assert movimento.id not in [m.id for m in pendentes_depois]


@pytest.mark.asyncio
async def test_obter_categoria_mais_recente_por_padrao_encontra_por_descricao_normalizada(db_session):
    from ava.financas.categorizacao_automatica import padrao_de_descricao

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=20, nivel_extracao=0, dados_extraidos={}
    )
    categoria = await _categoria(db_session, nome="Supermercado")
    await db_session.commit()

    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 5),
        valor=Decimal("-30.00"),
        descricao="COMPRA ELEC 123456 MERCADONA GONDOMAR",
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("30.00"),
        data=date(2026, 7, 5),
        origem="extrato",
        conta_id=conta.id,
        linha_extrato_id=linha.id,
        linhas=[LinhaNova(valor=Decimal("30.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()
    assert movimento is not None

    # mesmo comerciante, número de referência diferente
    padrao = padrao_de_descricao("COMPRA ELEC 987654 MERCADONA GONDOMAR")

    encontrada = await movimento_repo.obter_categoria_mais_recente_por_padrao(
        db_session, tipo="saida", padrao=padrao, conta_id=conta.id
    )

    assert encontrada == categoria.id


@pytest.mark.asyncio
async def test_obter_categoria_mais_recente_por_padrao_devolve_none_sem_correspondencia(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    await db_session.commit()

    resultado = await movimento_repo.obter_categoria_mais_recente_por_padrao(
        db_session, tipo="saida", padrao="PADRAO INEXISTENTE #", conta_id=conta.id
    )
    assert resultado is None


@pytest.mark.asyncio
async def test_obter_categoria_mais_recente_por_padrao_nao_atravessa_contas_diferentes(db_session):
    # Achado de revisão: parse_banco_bpi devolve a MESMA descricao ("AMORTIZACAO DE CAPITAL", sem
    # nenhum dígito) tanto para Crédito Pessoal como para Mortgage & Loans/Hipotecário — sem
    # restringir por conta_id, categorizar a amortização de UM crédito ensinaria (erradamente) a
    # mesma categoria para o crédito completamente diferente da mesma família.
    from ava.financas.categorizacao_automatica import padrao_de_descricao

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    credito_pessoal = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    credito_habitacao = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Mortgage & Loans/Hipotecário",
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=22, nivel_extracao=0, dados_extraidos={}
    )
    categoria = await _categoria(db_session, nome="Amortização Crédito Pessoal")
    await db_session.commit()

    linha_pessoal = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=credito_pessoal.id,
        documento_id=documento.id,
        data=date(2026, 7, 25),
        valor=Decimal("-100.00"),
        descricao="AMORTIZACAO DE CAPITAL",
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("100.00"),
        data=date(2026, 7, 25),
        origem="extrato",
        conta_id=credito_pessoal.id,
        linha_extrato_id=linha_pessoal.id,
        linhas=[LinhaNova(valor=Decimal("100.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    padrao = padrao_de_descricao("AMORTIZACAO DE CAPITAL")

    # mesmo padrão e tipo, mas conta de crédito DIFERENTE — não deve encontrar a categoria.
    resultado = await movimento_repo.obter_categoria_mais_recente_por_padrao(
        db_session, tipo="saida", padrao=padrao, conta_id=credito_habitacao.id
    )
    assert resultado is None

    # a mesma conta continua a encontrar a sua própria categoria aprendida.
    resultado_mesma_conta = await movimento_repo.obter_categoria_mais_recente_por_padrao(
        db_session, tipo="saida", padrao=padrao, conta_id=credito_pessoal.id
    )
    assert resultado_mesma_conta == categoria.id


@pytest.mark.asyncio
async def test_obter_categoria_mais_recente_por_padrao_respeita_o_tipo(db_session):
    from ava.financas.categorizacao_automatica import padrao_de_descricao

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="À ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=21, nivel_extracao=0, dados_extraidos={}
    )
    categoria = await _categoria(db_session, nome="Supermercado")
    await db_session.commit()

    linha = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 5),
        valor=Decimal("-30.00"),
        descricao="TRF SEPA 123 EMPRESA X",
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("30.00"),
        data=date(2026, 7, 5),
        origem="extrato",
        conta_id=conta.id,
        linha_extrato_id=linha.id,
        linhas=[LinhaNova(valor=Decimal("30.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    padrao = padrao_de_descricao("TRF SEPA 456 EMPRESA X")

    # mesma descrição normalizada, mas tipo "entrada" — não deve casar com o "saida" acima.
    resultado = await movimento_repo.obter_categoria_mais_recente_por_padrao(
        db_session, tipo="entrada", padrao=padrao, conta_id=conta.id
    )
    assert resultado is None


@pytest.mark.asyncio
async def test_listar_por_conta_inclui_transferencias_como_origem_e_como_destino(db_session):
    # Uma transferência (ex. amortização de crédito) tem de aparecer no histórico de AMBAS as
    # contas envolvidas — a de origem (conta_id) e a de destino (conta_destino_id) — não só na
    # de origem, senão a conta de crédito nunca veria o pagamento que reduziu a sua dívida.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("457.33"),
        data=date(2026, 7, 25),
        origem="extrato",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[LinhaNova(valor=Decimal("457.33"))],
    )
    await db_session.commit()

    movimentos_a_ordem = await movimento_repo.listar_por_conta(db_session, conta_a_ordem.id)
    movimentos_credito = await movimento_repo.listar_por_conta(db_session, conta_credito.id)

    assert [m.id for m in movimentos_a_ordem] == [movimento.id]
    assert [m.id for m in movimentos_credito] == [movimento.id]


@pytest.mark.asyncio
async def test_listar_por_conta_filtra_por_busca_valor_e_data(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    await db_session.commit()

    async def _movimento(tipo, valor, data, descricao):
        return await movimento_repo.criar_movimento(
            db_session, tipo=tipo, valor=Decimal(valor), data=data, origem="manual",
            descricao=descricao, conta_id=conta.id, linhas=[LinhaNova(valor=Decimal(valor))],
        )

    supermercado = await _movimento("saida", "50.00", date(2026, 7, 5), "Compra Continente")
    farmacia = await _movimento("saida", "8.00", date(2026, 7, 10), "Farmácia Central")
    salario = await _movimento("entrada", "1500.00", date(2026, 7, 1), "Salário empresa X")
    await db_session.commit()

    resultado = await movimento_repo.listar_por_conta(db_session, conta.id, busca="continente")
    assert [m.id for m in resultado] == [supermercado.id]

    # Movimento.valor é sempre positivo (ver A-P3/A-P6) — comparação direta, sem abs().
    resultado = await movimento_repo.listar_por_conta(db_session, conta.id, valor_min=Decimal("10"))
    assert {m.id for m in resultado} == {supermercado.id, salario.id}

    resultado = await movimento_repo.listar_por_conta(db_session, conta.id, valor_max=Decimal("10"))
    assert [m.id for m in resultado] == [farmacia.id]

    resultado = await movimento_repo.listar_por_conta(
        db_session, conta.id, data_inicio=date(2026, 7, 3), data_fim=date(2026, 7, 8)
    )
    assert [m.id for m in resultado] == [supermercado.id]


@pytest.mark.asyncio
async def test_listar_transferencias_sem_categoria_filtra_corretamente(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )
    categoria = await _categoria(db_session, nome="Amortização")
    await db_session.commit()

    sem_categoria = await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("100.00"),
        data=date(2026, 7, 25),
        origem="extrato",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[LinhaNova(valor=Decimal("100.00"))],
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("200.00"),
        data=date(2026, 7, 25),
        origem="extrato",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[LinhaNova(valor=Decimal("200.00"), categoria_id=categoria.id)],
    )
    # movimento normal (não transferência) sem categoria — não deve aparecer aqui
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("50.00"),
        data=date(2026, 7, 25),
        origem="extrato",
        conta_id=conta_a_ordem.id,
        linhas=[LinhaNova(valor=Decimal("50.00"))],
    )
    await db_session.commit()

    resultado = await movimento_repo.listar_transferencias_sem_categoria(db_session)

    assert [m.id for m in resultado] == [sem_categoria.id]


@pytest.mark.asyncio
async def test_listar_transferencias_sem_categoria_filtra_por_valor_e_data(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )

    pequena = await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("100.00"), data=date(2026, 7, 5),
        origem="extrato", conta_id=conta_a_ordem.id, conta_destino_id=conta_credito.id,
        linhas=[LinhaNova(valor=Decimal("100.00"))],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("900.00"), data=date(2026, 7, 20),
        origem="extrato", conta_id=conta_a_ordem.id, conta_destino_id=conta_credito.id,
        linhas=[LinhaNova(valor=Decimal("900.00"))],
    )
    await db_session.commit()

    resultado = await movimento_repo.listar_transferencias_sem_categoria(db_session, valor_max=Decimal("500"))
    assert [m.id for m in resultado] == [pequena.id]

    resultado = await movimento_repo.listar_transferencias_sem_categoria(
        db_session, data_inicio=date(2026, 7, 1), data_fim=date(2026, 7, 10)
    )
    assert [m.id for m in resultado] == [pequena.id]


@pytest.mark.asyncio
async def test_fluxo_entre_soma_entradas_e_saidas(db_session):
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await fabrica_criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="100.00", data=date(2026, 8, 2)
    )
    await fabrica_criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="30.00", data=date(2026, 8, 3)
    )
    await db_session.commit()

    entradas, saidas = await movimento_repo.fluxo_entre(
        db_session, conta.id, de=date(2026, 8, 1), ate=date(2026, 8, 31)
    )
    assert entradas == Decimal("100.00")
    assert saidas == Decimal("30.00")


@pytest.mark.asyncio
async def test_fluxo_entre_exclui_a_data_de_inicio_e_inclui_a_de_fim(db_session):
    # A ancora ja contem o que aconteceu ate a sua data, inclusive. Contar de novo o movimento
    # do proprio dia da ancora somava-o duas vezes.
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await fabrica_criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="10.00", data=date(2026, 8, 1)
    )
    await fabrica_criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="20.00", data=date(2026, 8, 31)
    )
    await db_session.commit()

    entradas, saidas = await movimento_repo.fluxo_entre(
        db_session, conta.id, de=date(2026, 8, 1), ate=date(2026, 8, 31)
    )
    assert saidas == Decimal("20.00")


@pytest.mark.asyncio
async def test_fluxo_entre_conta_a_transferencia_dos_dois_lados(db_session):
    # A mesma transferencia sai de uma conta e entra noutra.
    titular, ordem = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    credito = await fabrica_criar_conta(db_session, titular=titular, tipo="emprestimo", nome="Credito")
    await criar_transferencia(
        db_session, titular=titular, origem=ordem, destino=credito, valor="460.00", data=date(2026, 8, 5)
    )
    await db_session.commit()

    e_ordem, s_ordem = await movimento_repo.fluxo_entre(db_session, ordem.id, de=None, ate=date(2026, 8, 31))
    assert (e_ordem, s_ordem) == (Decimal("0"), Decimal("460.00"))

    e_credito, s_credito = await movimento_repo.fluxo_entre(db_session, credito.id, de=None, ate=date(2026, 8, 31))
    assert (e_credito, s_credito) == (Decimal("460.00"), Decimal("0"))


@pytest.mark.asyncio
async def test_fluxo_entre_sem_movimentos_devolve_zeros(db_session):
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await db_session.commit()

    assert await movimento_repo.fluxo_entre(
        db_session, conta.id, de=None, ate=date(2026, 8, 31)
    ) == (Decimal("0"), Decimal("0"))
