import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app
from ava.repositories import documento_repo, fila_repo, obrigacao_repo


def _client_para(db_session, extra_overrides: dict | None = None):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    for dependencia, override in (extra_overrides or {}).items():
        app.dependency_overrides[dependencia] = override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_home_mostra_proxima_obrigacao(db_session):
    await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="iuc",
        descricao="Pagamento do IUC",
        data_limite=date.today() + timedelta(days=10),
        origem="regra",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert "Pagamento do IUC" in resposta.text


@pytest.mark.asyncio
async def test_home_liquidez_reflete_movimentos_depois_da_ancora(db_session):
    # REGRESSAO (revisao final, achado 5): a "Liquidez" da home lia obter_saldo_em_data (a
    # ancora crua no fim do mes) em vez do saldo DERIVADO -- ignorava tudo o que o utilizador
    # tivesse registado a mao desde o ultimo extrato.
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo
    from tests.fabricas import criar_movimento

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date.today().replace(day=1), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="150.00", data=date.today(), conta=conta, titular=titular
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert "850,00" in resposta.text


@pytest.mark.asyncio
async def test_home_mostra_resumo_do_mes_selecionado(db_session):
    # Cobre despesas E rendimentos (Tarefa 5 só testou tipo="saida"), agrupamento por categoria
    # dentro de "Encargos financeiros" (duas categorias somadas, para provar que a agregação não
    # é apenas o valor de uma categoria isolada) e a exclusão de movimentos fora do período
    # selecionado — antes e depois da fronteira do mês — para provar que o filtro de datas
    # (calendar.monthrange) está realmente a excluir, não só a incluir.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )

    grupo_alimentacao = await categoria_repo.criar_grupo(db_session, nome="Alimentação Teste")
    categoria_supermercado = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_alimentacao.id, nome="Supermercado Teste", tipo="despesa", natureza="variavel"
    )
    grupo_encargos = await categoria_repo.criar_grupo(db_session, nome="Encargos financeiros")
    categoria_juros = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_encargos.id, nome="Juros Teste", tipo="despesa", natureza="variavel"
    )
    categoria_comissao = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_encargos.id, nome="Comissão Teste", tipo="despesa", natureza="variavel"
    )
    grupo_rendimentos = await categoria_repo.criar_grupo(db_session, nome="Rendimentos Teste")
    categoria_salario = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_rendimentos.id, nome="Salário Teste", tipo="receita", natureza="extraordinario"
    )
    await db_session.flush()

    async def _movimento(tipo, valor, data, categoria_id):
        await movimento_repo.criar_movimento(
            db_session, tipo=tipo, valor=Decimal(valor), data=data,
            origem="manual", descricao="teste", conta_id=conta.id, registado_por=titular.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal(valor), categoria_id=categoria_id)],
        )

    # Dentro do período (julho de 2026):
    await _movimento("saida", "50.00", date(2026, 7, 5), categoria_supermercado.id)
    await _movimento("saida", "15.00", date(2026, 7, 20), categoria_juros.id)
    await _movimento("saida", "5.00", date(2026, 7, 20), categoria_comissao.id)
    await _movimento("entrada", "1000.00", date(2026, 7, 1), categoria_salario.id)
    # Fora do período — antes do início do mês e depois do último dia (fronteira monthrange):
    await _movimento("saida", "999.00", date(2026, 6, 30), categoria_supermercado.id)
    await _movimento("saida", "888.00", date(2026, 8, 1), categoria_supermercado.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/?periodo=2026-07")

    assert resposta.status_code == 200
    # Categorias de despesa e de rendimento dentro do período aparecem.
    assert "Supermercado Teste" in resposta.text
    assert "Juros Teste" in resposta.text
    assert "Comissão Teste" in resposta.text
    assert "Salário Teste" in resposta.text
    # Totais do período: despesas = 50+15+5 = 70.00; rendimentos = 1000.00 (só tipo="entrada").
    assert "70,00" in resposta.text
    assert "1.000,00" in resposta.text
    # Encargos financeiros soma as DUAS categorias do grupo (15+5=20.00) — não o valor de uma só.
    assert "20,00" in resposta.text
    # Movimentos fora do período (antes e depois da fronteira do mês) não podem aparecer.
    assert "999" not in resposta.text
    assert "888" not in resposta.text


@pytest.mark.asyncio
async def test_home_mostra_percentagens_por_grupo_e_por_categoria(db_session):
    # Visão macro (grupo) + detalhe colorido (categoria dentro do grupo) pedidos pelo utilizador
    # para "Despesas por categoria" — ver dashboard._despesas_por_grupo.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação Percent")
    categoria_a = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado Percent", tipo="despesa", natureza="variavel"
    )
    categoria_b = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Restaurantes Percent", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()

    async def _movimento(valor, categoria_id):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal(valor), data=date(2026, 7, 10),
            origem="manual", descricao="teste", conta_id=conta.id, registado_por=titular.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal(valor), categoria_id=categoria_id)],
        )

    await _movimento("60.00", categoria_a.id)
    await _movimento("40.00", categoria_b.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/?periodo=2026-07")

    assert resposta.status_code == 200
    # O total do grupo aparece em euros no cabeçalho da secção (60+40).
    assert "100,00" in resposta.text
    # Dentro do grupo, cada categoria mostra o seu peso relativo: 60/100 e 40/100. A % do GRUPO
    # face ao total geral deixou de ser renderizada no redesenho (o lugar dela passou a ser a
    # barra de orçamento, ver home.html) — continua a ser calculada por _despesas_por_grupo e é
    # testada diretamente em test_despesas_por_grupo_percentagem_relativa_ao_total_geral.
    assert '<div class="progress-pct">60%</div>' in resposta.text
    assert '<div class="progress-pct">40%</div>' in resposta.text


def test_despesas_por_grupo_percentagem_relativa_ao_total_geral():
    # Com um só grupo a % é sempre 100% (caso trivial) — isto prova que com VÁRIOS grupos a de
    # cada um é relativa ao total geral, e que a de cada categoria é relativa ao PRÓPRIO grupo.
    #
    # Testa a função diretamente, e não a página: o redesenho deixou de renderizar a % do grupo
    # (passou a mostrar o total em euros e, havendo orçamento, a barra de execução). O cálculo
    # continua a existir e continua a ser o que alimenta essa secção, por isso continua a merecer
    # cobertura — mas ao nível onde vive, em vez de através de markup que já não o mostra.
    import uuid as _uuid

    from ava.api.dashboard import _despesas_por_grupo
    from ava.models.categoria import Categoria
    from ava.models.grupo_categoria import GrupoCategoria

    grupo_a = GrupoCategoria(id=_uuid.uuid4(), nome="Grupo A Percent")
    grupo_b = GrupoCategoria(id=_uuid.uuid4(), nome="Grupo B Percent")
    cat_a1 = Categoria(id=_uuid.uuid4(), grupo_id=grupo_a.id, nome="A1", tipo="despesa")
    cat_a2 = Categoria(id=_uuid.uuid4(), grupo_id=grupo_a.id, nome="A2", tipo="despesa")
    cat_b1 = Categoria(id=_uuid.uuid4(), grupo_id=grupo_b.id, nome="B1", tipo="despesa")

    resultado = _despesas_por_grupo(
        [
            (grupo_a, cat_a1, Decimal("50.00")),
            (grupo_a, cat_a2, Decimal("20.00")),
            (grupo_b, cat_b1, Decimal("30.00")),
        ],
        Decimal("100.00"),
    )

    # Ordenado por total desc: A (70) antes de B (30).
    assert [entrada["grupo"].nome for entrada in resultado] == ["Grupo A Percent", "Grupo B Percent"]
    # % do grupo é relativa ao total geral (70/100 e 30/100), não 100% para cada um.
    assert resultado[0]["percent"] == pytest.approx(70.0)
    assert resultado[1]["percent"] == pytest.approx(30.0)
    # % da categoria é relativa ao PRÓPRIO grupo (50/70 e 20/70), não ao total geral.
    percentagens_a = [item["percent"] for item in resultado[0]["categorias"]]
    assert percentagens_a == pytest.approx([50 / 70 * 100, 20 / 70 * 100])


@pytest.mark.asyncio
async def test_home_periodo_omisso_usa_mes_atual(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200


@pytest.mark.asyncio
async def test_home_recusa_titular_id_invalido_sem_rebentar(db_session):
    # Achado da revisao final de 2026-08-20: uuid.UUID(titular_id) sem guarda levantava
    # ValueError -> 500 nao tratado para um valor de query nao parsavel (mesmo padrao ja
    # corrigido em /insights).
    async with _client_para(db_session) as client:
        resposta = await client.get("/?titular_id=nao-e-um-uuid")

    assert resposta.status_code == 200


@pytest.mark.asyncio
async def test_home_mostra_botao_de_despesa_rapida_por_cartao_de_refeicao(db_session):
    # Achado da revisao final de 2026-08-20: cartoes_refeicao era calculado em home() mas nunca
    # chegava ao contexto do template -- {% if cartoes_refeicao %} ficava sempre falso e os
    # botoes "coffee <nome>" (atalho para /registo com a conta pre-selecionada) nunca apareciam.
    from ava.repositories import conta_repo
    from tests.fabricas import criar_titular_e_conta

    titular, _ = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    cartao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred",
        tipo="cartao_refeicao", nome="Cartão Refeição - Nuno",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert f'href="/registo?conta_id={cartao.id}&tipo=despesa"' in resposta.text
    assert "Nuno" in resposta.text


@pytest.mark.asyncio
async def test_prazos_lista_obrigacoes_pendentes(db_session):
    await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="inspecao",
        descricao="Inspeção periódica",
        data_limite=date.today() + timedelta(days=20),
        origem="regra",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/prazos")

    assert resposta.status_code == 200
    assert "Inspeção periódica" in resposta.text


@pytest.mark.asyncio
async def test_revisao_lista_documentos_em_revisao_manual(db_session):
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=2,
        nivel_extracao=1,
        dados_extraidos={},
        estado_validacao="revisao_manual",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/revisao")

    assert resposta.status_code == 200
    assert str(documento.paperless_document_id) in resposta.text


@pytest.mark.asyncio
async def test_falhas_lista_itens_com_erro(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=3, nivel_extracao=1, dados_extraidos={}
    )
    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto")
    await fila_repo.marcar_erro(db_session, item.id, "timeout do modelo")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/falhas")

    assert resposta.status_code == 200
    assert "timeout do modelo" in resposta.text


@pytest.mark.asyncio
async def test_post_aprovar_revisao_persiste_e_devolve_fragmento(db_session):
    from ava.api.deps import get_paperless_client

    dados_fatura = {
        "fornecedor_nome": "MEO",
        "nif_emissor": None,
        "iban": None,
        "valor_total": "29.99",
        "data_limite_pagamento": "2026-08-01",
        "linhas": [],
        "consumo": None,
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=8,
        nivel_extracao=1,
        dados_extraidos=dados_fatura,
        estado_validacao="revisao_manual",
    )
    await db_session.commit()

    class FakePaperlessDeps:
        async def obter_id_de_tag(self, nome: str) -> int:
            return 1

        async def remover_tag(self, document_id: int, tag_id: int) -> None:
            pass

    async with _client_para(db_session, {get_paperless_client: lambda: FakePaperlessDeps()}) as client:
        resposta = await client.post(f"/revisao/{documento.id}/aprovar")

    assert resposta.status_code == 200
    assert "Aprovado" in resposta.text

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_get_movimentos_lista_pendentes(db_session):
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=9, nivel_extracao=0, dados_extraidos={}
    )
    movimento = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 9),
        valor=Decimal("-15.00"),
        descricao="COMPRA X",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, movimento.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "COMPRA X" in resposta.text


@pytest.mark.asyncio
async def test_movimentos_lista_cada_linha_individualmente(db_session):
    # Duas linhas do mesmo comerciante aparecem como DUAS entradas, cada uma com a sua data e
    # valor — é isto que permite dar-lhes ativos diferentes.
    from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=90, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()
    for dia, valor in ((1, Decimal("-60.00")), (5, Decimal("-55.00"))):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=conta.id, documento_id=documento.id,
            data=date(2026, 8, dia), valor=valor, descricao=f"GALP AREAS 7777{dia}",
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    # Os dois valores aparecem, cada um o seu — não um total agregado de 115,00.
    assert "60,00" in resposta.text
    assert "55,00" in resposta.text
    assert "115,00" not in resposta.text


@pytest.mark.asyncio
async def test_movimentos_mostra_a_data_de_cada_linha(db_session):
    # Sem agrupamento, a data deixa de ser ambígua e passa a ser mostrada.
    from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=91, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 14), valor=Decimal("-42.00"), descricao="LIDL 88888",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "14/08/2026" in resposta.text


@pytest.mark.asyncio
async def test_get_movimentos_filtra_por_busca_valor_e_data(db_session):
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=90, nivel_extracao=0, dados_extraidos={}
    )

    async def _linha(data, valor, descricao):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=conta.id, documento_id=documento.id, data=data, valor=Decimal(valor),
            descricao=descricao,
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)

    await _linha(date(2026, 7, 5), "-50.00", "COMPRA CONTINENTE XYZ")
    await _linha(date(2026, 7, 10), "-8.00", "FARMACIA CENTRAL")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos", params={"busca": "continente"})
    assert "COMPRA CONTINENTE XYZ" in resposta.text
    assert "FARMACIA CENTRAL" not in resposta.text

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos", params={"valor_max": "10"})
    assert "FARMACIA CENTRAL" in resposta.text
    assert "COMPRA CONTINENTE XYZ" not in resposta.text

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos", params={"busca": "inexistente"})
    assert "movimentos pendentes para os filtros atuais" in resposta.text


@pytest.mark.asyncio
async def test_get_movimentos_com_filtro_malformado_e_ignorado_sem_rebentar(db_session):
    # Achado da revisão: o comportamento central de _parse_filtros_movimentos é ignorar em
    # silêncio um valor malformado (em vez de 422/500) — mas nada testava isso diretamente.
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=91, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 5),
        valor=Decimal("-15.00"), descricao="COMPRA X",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            "/movimentos", params={"valor_min": "abc", "data_inicio": "31-07-2026"}
        )
    assert resposta.status_code == 200
    assert "COMPRA X" in resposta.text  # filtro malformado ignorado — linha continua a aparecer


@pytest.mark.asyncio
async def test_movimentos_de_conta_com_filtro_malformado_e_ignorado_sem_rebentar(db_session):
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Teste"
    )
    await db_session.flush()
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 5),
        origem="manual", descricao="Supermercado Continente", conta_id=conta.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("50.00"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/patrimonio/contas/{conta.id}", params={"valor_min": "abc", "data_inicio": "31-07-2026"}
        )
    assert resposta.status_code == 200
    assert "Supermercado Continente" in resposta.text


@pytest.mark.asyncio
async def test_get_movimentos_lista_cada_linha_do_mesmo_comerciante_separadamente(db_session):
    # Inverso do teste anterior: o agrupamento por comerciante foi removido para cada despesa
    # poder receber o seu próprio ativo (ver a spec 2026-08-06).
    from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=92, nivel_extracao=0, dados_extraidos={}
    )
    await db_session.flush()

    for referencia, valor in (("111111", "10.00"), ("222222", "15.50"), ("333333", "20.00")):
        linha = await linha_extrato_repo.criar_linha(
            db_session, conta_id=conta.id, documento_id=documento.id,
            data=date(2026, 7, 10), valor=-Decimal(valor),
            descricao=f"COMPRA ELEC {referencia} MERCADONA GONDOMAR",
        )
        await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    outra = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 7, 11), valor=-Decimal("30.00"),
        descricao="COMPRA ELEC 444444 PINGO DOCE MAIA",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, outra.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    # As três linhas do mesmo comerciante aparecem as três, não uma agregada.
    assert resposta.text.count("MERCADONA GONDOMAR") == 3
    # Cada uma com o seu valor; o total agregado de 45,50 deixa de existir.
    assert "10,00" in resposta.text
    assert "15,50" in resposta.text
    assert "20,00" in resposta.text
    assert "45,50" not in resposta.text
    assert "PINGO DOCE MAIA" in resposta.text


@pytest.mark.asyncio
async def test_get_movimentos_mostra_sinal_e_cor_consoante_saida_ou_entrada(db_session):
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=12, nivel_extracao=0, dados_extraidos={}
    )
    linha_saida = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 9),
        valor=Decimal("-30.00"),
        descricao="COMPRA ELEC 111111 MERCADONA GONDOMAR",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_saida.id)
    linha_entrada = await linha_extrato_repo.criar_linha(
        db_session,
        conta_id=conta.id,
        documento_id=documento.id,
        data=date(2026, 7, 9),
        valor=Decimal("1200.00"),
        descricao="TRF CR SEPA+ 222222 DE EMPRESA X",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha_entrada.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    # O redesenho deixou de prefixar o sinal (−/+): o valor é sempre a magnitude e a direção vem
    # só da cor (text-negative / text-positive), atribuída por grupo.tipo em movimentos.html.
    assert "30,00" in resposta.text
    assert "text-negative" in resposta.text
    assert "1.200,00" in resposta.text
    assert "text-positive" in resposta.text


@pytest.mark.asyncio
async def test_get_movimentos_mostra_movimento_de_ficheiro_sem_categoria(db_session):
    # Achado 1 da revisão final da spec 2026-08-09: um movimento importado do BPI Net sem padrão
    # aprendido (origem="ficheiro") tem de aparecer aqui, tal como um manual — senão fica
    # invisível e não conta para orçamento nenhum (totais_por_categoria faz inner join com
    # Categoria).
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("65.89"),
        data=date(2026, 8, 1),
        origem="ficheiro",
        descricao="COMPRA ELEC PRIMARK",
        conta_id=conta.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("65.89"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "COMPRA ELEC PRIMARK" in resposta.text


@pytest.mark.asyncio
async def test_post_categorizar_movimento_de_ficheiro_grava_a_categoria(db_session):
    # Contrapartida do teste acima: aparecer na lista não basta se não puder ser categorizado —
    # a rota devolvia 404 para qualquer origem fora de ORIGENS_REGISTO_MANUAL.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("65.89"),
        data=date(2026, 8, 1),
        origem="ficheiro",
        descricao="COMPRA ELEC PRIMARK",
        conta_id=conta.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("65.89"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={"categoria_id": str(categoria.id), "conta_id": str(conta.id)},
        )

    assert resposta.status_code == 200
    atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert atualizado.linhas[0].categoria_id == categoria.id


@pytest.mark.asyncio
async def test_outlier_check_mostra_aviso_para_valor_muito_acima_do_historico(db_session):
    from ava.repositories import categoria_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Saúde")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Consultas", tipo="despesa", natureza="variavel"
    )
    for dia, valor in ((1, "50.00"), (2, "50.00"), (3, "50.00")):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal(valor), data=date(2026, 7, dia),
            origem="manual", conta_id=conta.id, titular_id=titular.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal(valor), categoria_id=categoria.id)],
        )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/movimentos/outlier-check?categoria_id={categoria.id}&valor=200.00"
        )

    assert resposta.status_code == 200
    assert "Isto é 4x o normal para Consultas" in resposta.text


@pytest.mark.asyncio
async def test_outlier_check_sem_aviso_para_valor_normal(db_session):
    from ava.repositories import categoria_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Saúde")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Consultas", tipo="despesa", natureza="variavel"
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 1),
        origem="manual", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("50.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/movimentos/outlier-check?categoria_id={categoria.id}&valor=55.00"
        )

    assert resposta.status_code == 200
    assert resposta.text.strip() == ""


@pytest.mark.asyncio
async def test_outlier_check_recusa_categoria_id_invalido_sem_rebentar(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos/outlier-check?categoria_id=lixo&valor=50.00")

    assert resposta.status_code == 200
    assert resposta.text.strip() == ""


@pytest.mark.asyncio
async def test_outlier_check_recusa_valor_invalido_sem_rebentar(db_session):
    from ava.repositories import categoria_repo

    grupo = await categoria_repo.criar_grupo(db_session, nome="Saúde")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Consultas", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/movimentos/outlier-check?categoria_id={categoria.id}&valor=nao-e-numero"
        )

    assert resposta.status_code == 200
    assert resposta.text.strip() == ""


@pytest.mark.asyncio
async def test_outlier_check_categoria_inexistente_devolve_vazio(db_session):
    import uuid as _uuid

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/movimentos/outlier-check?categoria_id={_uuid.uuid4()}&valor=50.00"
        )

    assert resposta.status_code == 200
    assert resposta.text.strip() == ""


@pytest.mark.asyncio
async def test_categoria_movimentos_lista_despesas_do_periodo(db_session):
    from ava.repositories import categoria_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("42.50"), data=date(2026, 7, 15),
        origem="manual", conta_id=conta.id, titular_id=titular.id, descricao="CONTINENTE",
        linhas=[movimento_repo.LinhaNova(valor=Decimal("42.50"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/categorias/{categoria.id}/movimentos?periodo=2026-07")

    assert resposta.status_code == 200
    assert "CONTINENTE" in resposta.text
    assert "42,50" in resposta.text
    assert "15/07/2026" in resposta.text
    assert "Trocar categoria" in resposta.text


@pytest.mark.asyncio
async def test_categoria_movimentos_sem_despesas_mostra_estado_vazio(db_session):
    from ava.repositories import categoria_repo

    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/categorias/{categoria.id}/movimentos?periodo=2026-07")

    assert resposta.status_code == 200
    assert "Sem despesas nesta categoria" in resposta.text


@pytest.mark.asyncio
async def test_categoria_movimentos_ignora_despesa_fora_do_periodo(db_session):
    from ava.repositories import categoria_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("42.50"), data=date(2026, 6, 15),
        origem="manual", conta_id=conta.id, titular_id=titular.id, descricao="CONTINENTE",
        linhas=[movimento_repo.LinhaNova(valor=Decimal("42.50"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/categorias/{categoria.id}/movimentos?periodo=2026-07")

    assert resposta.status_code == 200
    assert "Sem despesas nesta categoria" in resposta.text


@pytest.mark.asyncio
async def test_categoria_movimentos_sem_periodo_usa_mes_atual(db_session):
    from ava.repositories import categoria_repo

    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/categorias/{categoria.id}/movimentos")

    assert resposta.status_code == 200
    assert "Sem despesas nesta categoria" in resposta.text


@pytest.mark.asyncio
async def test_categorizar_movimento_com_conta_nao_muda_a_conta_autoritativa(db_session):
    # Achado 1 da revisao da revisao final: um movimento de ficheiro ja traz a conta autoritativa
    # (a escolhida na importacao). O formulario tem um <select> sem pre-selecao, e escrever
    # conta_id incondicionalmente deixava um engano no dropdown mover o movimento para OUTRA
    # conta, corrompendo o saldo derivado das duas -- sem caminho de retorno no UI, porque o
    # movimento sai da lista "por categorizar" assim que ganha categoria.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta_certa = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    conta_errada = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="poupanca", nome="Poupança"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("65.89"),
        data=date(2026, 8, 1),
        origem="ficheiro",
        descricao="COMPRA ELEC PRIMARK",
        conta_id=conta_certa.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("65.89"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        # O utilizador engana-se e submete a conta ERRADA no dropdown.
        resposta = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={"categoria_id": str(categoria.id), "conta_id": str(conta_errada.id)},
        )

    assert resposta.status_code == 200
    atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert atualizado.conta_id == conta_certa.id  # a conta autoritativa nao mudou
    assert atualizado.linhas[0].categoria_id == categoria.id  # mas a categoria gravou na mesma


@pytest.mark.asyncio
async def test_categorizar_movimento_sem_conta_recebe_a_submetida(db_session):
    # Contraste: um movimento manual antigo SEM conta (o caso que a rota sempre serviu) continua
    # a receber a conta escolhida no formulario -- a correcao e condicional, nao uma remocao.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("12.00"),
        data=date(2026, 8, 1),
        origem="manual",
        descricao="Registo rapido sem conta",
        conta_id=None,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("12.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={"categoria_id": str(categoria.id), "conta_id": str(conta.id)},
        )

    assert resposta.status_code == 200
    atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert atualizado.conta_id == conta.id
    assert atualizado.linhas[0].categoria_id == categoria.id


@pytest.mark.asyncio
async def test_post_categorizar_movimento_de_extrato_continua_a_dar_404(db_session):
    # Contraste: um movimento que já veio confirmado pelo extrato não é "por categorizar à mão"
    # no mesmo sentido — a rota continua a recusá-lo, prova que a mudança é por ORIGEM e não uma
    # abertura geral.
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("10.00"),
        data=date(2026, 8, 1),
        origem="extrato",
        descricao="COMPRA ELEC",
        conta_id=conta.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("10.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={"categoria_id": str(categoria.id), "conta_id": str(conta.id)},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_get_movimentos_mostra_transferencias_por_categorizar(db_session):
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("457.33"),
        data=date(2026, 7, 25),
        origem="extrato",
        descricao="Amortização de capital",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("457.33"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "Mortgage & Loans" in resposta.text
    assert "457,33" in resposta.text


@pytest.mark.asyncio
async def test_post_movimento_transferencia_categoriza_e_aplica_ao_grupo(db_session):
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Encargos financeiros")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Amortização Mortgage & Loans", tipo="despesa", natureza="variavel"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("457.33"),
        data=date(2026, 7, 25),
        origem="extrato",
        descricao="Amortização de capital",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("457.33"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/transferencia", data={"categoria_id": str(categoria.id)}
        )

    assert resposta.status_code == 200

    ainda_por_categorizar = await movimento_repo.listar_transferencias_sem_categoria(db_session)
    assert ainda_por_categorizar == []


@pytest.mark.asyncio
async def test_post_movimento_despesa_resolve_e_cria_movimento(db_session):
    from ava.repositories import categoria_repo, conta_repo, linha_extrato_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred", tipo="cartao_refeicao", nome="Cartão Edenred"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=10, nivel_extracao=0, dados_extraidos={}
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    movimento = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 10), valor=Decimal("-8.50")
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, movimento.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/despesa", data={"categoria_id": str(categoria.id)}
        )

    assert resposta.status_code == 200

    despesas = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31), tipo="saida"
    )
    assert len(despesas) == 1
    assert despesas[0].valor == Decimal("8.50")
    assert despesas[0].linhas[0].categoria_id == categoria.id


@pytest.mark.asyncio
async def test_patrimonio_mostra_saldo_por_conta_e_liquido(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_divida = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="divida", nome="Mortgage & Loans"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ordem.id, data=date(2026, 7, 31), valor=Decimal("2000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_divida.id, data=date(2026, 7, 31), valor=Decimal("500.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "Conta à Ordem" in resposta.text
    assert "1.500,00" in resposta.text  # financeiro: 2000 - 500 (formatado com separador de milhares)


@pytest.mark.asyncio
async def test_patrimonio_usa_cartao_de_registo_nao_tabela(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 7, 31), valor=Decimal("2000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "Conta à Ordem" in resposta.text
    assert 'class="cartao-registo"' in resposta.text
    assert "<table" not in resposta.text
    # KPIs no par hero + linha secundária, como no resto do redesenho — não a grelha antiga.
    assert 'class="kpi-grid kpi-grid-hero"' in resposta.text
    assert 'class="kpi-grid kpi-grid-secundaria kpi-grid-secundaria-2col"' in resposta.text


@pytest.mark.asyncio
async def test_patrimonio_kpi_secundaria_usa_classe_de_2_colunas_nao_style_inline(db_session):
    # Achado de 2026-08-21 (revisão de mobile): "Total de Ativos" / "Total de Dívidas" tinham
    # style="grid-template-columns: repeat(2, 1fr)" inline -- mesma classe de bug já corrigida
    # para dashboard-grid-equal em 2026-08-20, especificidade mais alta do que a regra mobile
    # @media (max-width: 767px) .kpi-grid-secundaria { grid-template-columns: 1fr; }, por isso
    # nunca colapsava para uma coluna em mobile. kpi-grid-secundaria-2col só define as duas
    # colunas dentro de @media (min-width: 768px), por isso não compete com a regra mobile.
    from tests.fabricas import criar_titular_e_conta

    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert 'class="kpi-grid kpi-grid-secundaria kpi-grid-secundaria-2col"' in resposta.text
    assert "grid-template-columns: repeat(2, 1fr)" not in resposta.text


@pytest.mark.asyncio
async def test_patrimonio_usa_classe_para_duas_colunas_iguais_nao_style_inline(db_session):
    # Achado de 2026-08-20: as colunas "Ativos e Contas" / "Dívidas e Créditos" tinham
    # style="grid-template-columns: 1fr 1fr" inline -- especificidade mais alta do que a regra
    # mobile @media (max-width: 767px) .dashboard-grid { grid-template-columns: minmax(0, 1fr); }
    # em premium.css, por isso nunca colapsava para uma coluna em mobile (os cartões de Dívidas e
    # Créditos ficavam espremidos numa segunda coluna fora do ecrã). A classe
    # dashboard-grid-equal só define as duas colunas dentro de @media (min-width: 768px), por
    # isso não compete com a regra mobile.
    from tests.fabricas import criar_titular_e_conta

    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert 'class="dashboard-grid dashboard-grid-equal mt-8"' in resposta.text
    assert "grid-template-columns: 1fr 1fr" not in resposta.text


@pytest.mark.asyncio
async def test_grafico_de_evolucao_vive_em_patrimonio_nao_no_dashboard(db_session):
    # O dashboard e uma visao do MES; a evolucao do patrimonio e uma serie historica, sem relacao
    # com o periodo selecionado -- por isso vive em /patrimonio, nao em /.
    async with _client_para(db_session) as client:
        resposta_home = await client.get("/")
        resposta_patrimonio = await client.get("/patrimonio")

    assert "grafico-patrimonio" not in resposta_home.text
    assert "Evolução do Património" not in resposta_home.text
    assert "grafico-patrimonio" in resposta_patrimonio.text
    assert "Evolução do Património" in resposta_patrimonio.text


@pytest.mark.asyncio
async def test_patrimonio_separa_ativos_e_creditos_por_categoria(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_habitacao = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="CGD",
        tipo="divida",
        nome="Mortgage & Loans CGD",
        categoria_divida="habitacao",
    )
    conta_sem_categoria = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="Cetelem",
        tipo="divida",
        nome="Dívida Antiga",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ordem.id, data=date(2026, 7, 31), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_habitacao.id, data=date(2026, 7, 31), valor=Decimal("300.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_sem_categoria.id, data=date(2026, 7, 31), valor=Decimal("100.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "Ativos e Contas" in resposta.text
    assert "Créditos" in resposta.text
    assert "Conta à Ordem" in resposta.text
    assert "Mortgage & Loans CGD" in resposta.text
    assert "Habitação" in resposta.text  # rótulo da categoria de dívida
    assert "Dívida Antiga" in resposta.text
    assert "Outro" in resposta.text  # conta de dívida sem categoria cai no grupo "Outro"


@pytest.mark.asyncio
async def test_patrimonio_agrupa_investimentos_por_categoria(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    # Duas contas de investimento em categorias diferentes (nomes sem sobreposição textual com
    # os rótulos de categoria) — assim uma conta a aparecer na página sem estar agrupada por
    # categoria_investimento (ex.: a cair em contas_simples) não passa por acidente: os
    # cabeçalhos <h3> "PPR"/"ETF" só existem quando a lógica de agrupamento por categoria
    # realmente corre.
    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta_etf = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="XTB", tipo="investimento", nome="Fundo Global",
    )
    conta_etf.categoria_investimento = "etf"
    conta_ppr = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Fidelidade", tipo="investimento", nome="Reforma Segura",
    )
    conta_ppr.categoria_investimento = "ppr"
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_etf.id, data=date(2026, 7, 1), valor=Decimal("5000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ppr.id, data=date(2026, 7, 1), valor=Decimal("3000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    # Os rótulos de categoria só surgem como cabeçalho <h3> de grupo (patrimonio.html) — se a
    # conta caísse em contas_simples (tabela plana, sem agrupamento), este markup não existiria.
    assert ">ETF</h3>" in resposta.text
    assert ">PPR</h3>" in resposta.text
    assert "Fundo Global" in resposta.text
    assert "Reforma Segura" in resposta.text

    # Confirma que cada conta está aninhada sob o grupo correto (e não só presente algures na
    # página): CATEGORIA_INVESTIMENTO_LABELS itera "ppr" antes de "etf", logo a ordem esperada
    # no HTML renderizado é: cabeçalho PPR, "Reforma Segura", cabeçalho ETF, "Fundo Global".
    indice_ppr = resposta.text.index(">PPR</h3>")
    indice_reforma_segura = resposta.text.index("Reforma Segura")
    indice_etf = resposta.text.index(">ETF</h3>")
    indice_fundo_global = resposta.text.index("Fundo Global")
    assert indice_ppr < indice_reforma_segura < indice_etf < indice_fundo_global


@pytest.mark.asyncio
async def test_patrimonio_separa_financeiro_de_total(db_session):
    # O financeiro assenta só em saldos reais; o total acrescenta as estimativas dos bens.
    # Sem a separação, uma estimativa de valor de carro contamina a métrica que se sabe exata.
    from ava.repositories import ativo_repo, ativo_valor_repo, conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 7, 31), valor=Decimal("2000.00")
    )
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date.today(), valor=Decimal("8000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "2.000,00" in resposta.text   # financeiro: só a conta
    assert "10.000,00" in resposta.text  # total: conta + carro


@pytest.mark.asyncio
async def test_patrimonio_marca_valor_projetado_como_estimado(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    # Observação antiga -> o valor de hoje é projetado.
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2020, 1, 1), valor=Decimal("20000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert "estimado" in resposta.text


@pytest.mark.asyncio
async def test_patrimonio_ativo_sem_avaliacao_nao_conta_como_zero(db_session):
    # Regressão: o teste anterior só verificava o texto "Sem avaliação" e nunca afirmava que o
    # total ficava inalterado — um refactor que fizesse um bem sem avaliação contribuir com zero
    # continuava a passar. Aqui a conta tem exatamente 2000, e com o bem a não contribuir nada
    # (None, não zero), Total de Ativos, Património Financeiro e Património Total têm todos de
    # mostrar o mesmo 2000 — nenhum pode aparecer diminuído nem aumentado pelo bem sem avaliação.
    from ava.repositories import ativo_repo, conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date.today(), valor=Decimal("2000.00")
    )
    await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Mota", tipo="mota")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "Mota" in resposta.text
    # Aparece na lista, mas sem valor — "não sei quanto vale" não é "vale nada".
    assert "Sem avaliação" in resposta.text
    # Asserção numérica: a linha da própria conta e os três KPIs (Total de Ativos, Património
    # Financeiro, Património Total) mostram todos exatamente 2.000,00 € — o bem sem avaliação
    # não subtraiu nem somou nada a nenhum deles.
    assert resposta.text.count("2.000,00 €") == 4


@pytest.mark.asyncio
async def test_patrimonio_mostra_o_saldo_derivado(db_session):
    # A pagina deixa de mostrar o numero cru da ancora e passa a mostrar o saldo DERIVADO
    # (ancora + movimentos desde ela) -- a ancora fica so em segundo plano, como proveniencia.
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo
    from tests.fabricas import criar_movimento

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="150.00", data=date(2026, 8, 5)
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert "850,00" in resposta.text     # derivado
    assert "1.000,00" in resposta.text   # a ancora, em segundo plano


@pytest.mark.asyncio
async def test_patrimonio_mostra_traco_em_conta_sem_ancora(db_session):
    # Nunca 0,00: numa conta de divida afirmaria que nao se deve nada (spec §3.2).
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI",
        tipo="cartao_credito", nome="Cartão Sem Saldo",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    assert resposta.status_code == 200
    assert "Cartão Sem Saldo" in resposta.text

    # Asserção específica ao VALOR desta conta, não à página inteira: base.html tem um travessão
    # num comentário dentro de um <script> no <head> (herdado por toda a página), por isso
    # `assert "—" in resposta.text` sozinho passaria mesmo sem a funcionalidade. Isolamos o
    # fragmento entre o nome da conta e o fecho da sua div de valor (cartão de registo, não
    # tabela) e afirmamos aí: o traço está presente, e nenhum valor monetário (nunca "0,00 €").
    indice_nome = resposta.text.index("Cartão Sem Saldo")
    indice_valor = resposta.text.index('class="cartao-registo-valor', indice_nome)
    indice_fim_valor = resposta.text.index("</div>", indice_valor)
    valor_html = resposta.text[indice_valor:indice_fim_valor]
    assert "—" in valor_html
    assert "€" not in valor_html


@pytest.mark.asyncio
async def test_patrimonio_total_usa_o_derivado(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo
    from tests.fabricas import criar_movimento

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="150.00", data=date(2026, 8, 5)
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/patrimonio")

    # O patrimonio financeiro passa a ser 850, nao 1000. A FORMULA nao muda -- muda a origem do
    # valor de cada conta.
    assert "850,00" in resposta.text


@pytest.mark.asyncio
async def test_home_kpi_patrimonio_total_usa_o_derivado(db_session):
    # O KPI mais visivel da app (dashboard.py:147, "Patrimonio Total") le serie_patrimonio[-1],
    # que apos a Task 10 e o ponto de HOJE, DERIVADO -- ancora mais os movimentos desde ela -- e
    # nao a ultima ancora confirmada. Nenhum teste cobria isto ainda, apesar de ser o numero mais
    # visivel da aplicacao.
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo
    from tests.fabricas import criar_movimento

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="150.00", data=date(2026, 8, 5)
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200

    # Isola o conteudo do proprio KPI (nao a pagina inteira): a mesma pagina mostra outros valores
    # em euros noutros KPIs, por isso uma asercao solta no texto inteiro nao provaria nada sobre
    # este KPI em particular. Isolar ao <div class="kpi-value blue"> e o unico jeito de o teste
    # passar SO quando o KPI mostra o derivado, e falhar se algum dia voltar a mostrar o valor cru
    # da ancora.
    indice_valor = resposta.text.index('kpi-value blue">')
    indice_fim = resposta.text.index("</div>", indice_valor)
    valor_kpi_html = resposta.text[indice_valor:indice_fim]

    assert "850,00" in valor_kpi_html    # derivado: 1000 - 150
    assert "1.000,00" not in valor_kpi_html  # nao o valor cru da ancora


@pytest.mark.asyncio
async def test_sidebar_usa_o_macro_de_navegacao_e_marca_o_link_ativo(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert 'class="sidebar"' in resposta.text
    # A classe "active" tem de estar ligada ao PRÓPRIO <a> de /movimentos, não só presente
    # algures na página.
    assert re.search(r'href="/movimentos"[^>]*class="[^"]*active', resposta.text)
    assert not re.search(r'href="/"[^>]*class="[^"]*active', resposta.text)


@pytest.mark.asyncio
async def test_get_ativo_novo_lista_titulares(db_session):
    from ava.repositories import titular_repo

    await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/ativos/novo")

    assert resposta.status_code == 200
    assert "Ana" in resposta.text


@pytest.mark.asyncio
async def test_post_ativo_novo_cria_ativo_e_avaliacao_de_compra(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/ativos/novo",
            data={
                "titular_id": str(titular.id),
                "nome": "Corsa",
                "tipo": "carro",
                "valor_atual": "8500.00",
                "data_aquisicao": "2022-03-10",
            },
        )

    assert resposta.status_code in (200, 303)

    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert len(ativos) == 1
    assert ativos[0].nome == "Corsa"
    assert ativos[0].titular_id == titular.id
    # data_aquisicao é o que alimenta as obrigações de inspeção/IUC (ver ava.obrigacoes.regras);
    # o formulário chegou a perder este campo na renomeação veiculo -> ativo.
    assert ativos[0].data_aquisicao == date(2022, 3, 10)

    # O valor introduzido vira a primeira observação, com origem "aquisicao" na data de compra.
    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id)
    assert len(historico) == 1
    assert historico[0].valor == Decimal("8500.00")
    assert historico[0].data == date(2022, 3, 10)
    assert historico[0].origem == "aquisicao"


@pytest.mark.asyncio
async def test_post_ativo_novo_sem_valor_nao_cria_avaliacao(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            "/ativos/novo",
            data={"titular_id": str(titular.id), "nome": "Mota", "tipo": "mota", "valor_atual": ""},
        )

    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id) == []


@pytest.mark.asyncio
async def test_post_ativo_novo_com_valor_malformado_cria_ativo_sem_avaliacao(db_session):
    # Entrada inválida é ignorada em silêncio, como nos restantes formulários: não cria
    # avaliação nenhuma, mas também não impede a criação do próprio ativo.
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/ativos/novo",
            data={"titular_id": str(titular.id), "nome": "Barco", "tipo": "outro",
                  "valor_atual": "abc"},
        )

    assert resposta.status_code in (200, 303)
    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert len(ativos) == 1
    assert ativos[0].nome == "Barco"
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id) == []


@pytest.mark.asyncio
async def test_post_ativo_novo_com_data_aquisicao_futura_nao_cria_avaliacao(db_session):
    # Mesmo defeito do ponto 2 (registar_avaliacao_ativo, /configuracoes/ativos), apanhado numa
    # terceira rota que tinha ficado de fora da lista original: data_aquisicao alimenta
    # diretamente a avaliação "aquisicao", e uma data futura corromperia o KPI de património e a
    # série do gráfico da home. Tratada como entrada malformada — como o valor malformado no
    # teste anterior — o ativo é criado na mesma, só a avaliação é que não.
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    data_futura = (date.today() + timedelta(days=1)).isoformat()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/ativos/novo",
            data={
                "titular_id": str(titular.id),
                "nome": "Corsa",
                "tipo": "carro",
                "valor_atual": "8500.00",
                "data_aquisicao": data_futura,
            },
        )

    assert resposta.status_code in (200, 303)
    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert len(ativos) == 1
    assert ativos[0].nome == "Corsa"
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id) == []


@pytest.mark.asyncio
async def test_get_titular_novo_mostra_formulario(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/titulares/novo")

    assert resposta.status_code == 200
    assert "Novo titular" in resposta.text


@pytest.mark.asyncio
async def test_get_conta_novo_lista_titulares(db_session):
    from ava.repositories import titular_repo

    await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/contas/novo")

    assert resposta.status_code == 200
    assert "Ana" in resposta.text


@pytest.mark.asyncio
async def test_get_conta_novo_mostra_campo_categoria_divida(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/contas/novo")

    assert resposta.status_code == 200
    assert 'name="categoria_divida"' in resposta.text
    assert "Habitação" in resposta.text


@pytest.mark.asyncio
async def test_get_conta_novo_mostra_badge_de_alertas_pendentes(db_session):
    # Regressão: form_conta_novo (e as outras 3 rotas de formulário) renderizam base.html mas
    # não passavam total_alertas — a badge da barra lateral desaparecia silenciosamente.
    await obrigacao_repo.criar_obrigacao(
        db_session,
        tipo="iuc",
        descricao="Pagamento do IUC",
        data_limite=date.today() + timedelta(days=10),
        origem="regra",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/contas/novo")

    assert resposta.status_code == 200
    assert 'class="badge-alert"' in resposta.text


@pytest.mark.asyncio
async def test_post_conta_novo_cria_conta_cartao_refeicao(db_session):
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/contas/novo",
            data={
                "titular_id": str(titular.id),
                "instituicao": "Edenred",
                "tipo": "cartao_refeicao",
                "nome": "Cartão Edenred",
            },
        )

    assert resposta.status_code in (200, 303)

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    assert contas[0].tipo == "cartao_refeicao"
    assert contas[0].nome == "Cartão Edenred"
    assert contas[0].categoria_divida is None


@pytest.mark.asyncio
async def test_post_conta_novo_cria_conta_divida_com_categoria(db_session):
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/contas/novo",
            data={
                "titular_id": str(titular.id),
                "instituicao": "CGD",
                "tipo": "divida",
                "nome": "Mortgage & Loans",
                "categoria_divida": "habitacao",
            },
        )

    assert resposta.status_code in (200, 303)

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    assert contas[0].tipo == "divida"
    assert contas[0].categoria_divida == "habitacao"


@pytest.mark.asyncio
async def test_get_rendimento_recorrente_novo_lista_titulares_e_contas(db_session):
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred", tipo="cartao_refeicao", nome="Cartão Edenred"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/rendimentos-recorrentes/novo")

    assert resposta.status_code == 200
    assert "Nuno" in resposta.text
    assert "Cartão Edenred" in resposta.text


@pytest.mark.asyncio
async def test_post_rendimento_recorrente_novo_com_conta(db_session):
    from ava.repositories import categoria_repo, conta_repo, recorrente_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred", tipo="cartao_refeicao", nome="Cartão Edenred"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Rendimentos")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Subsídio de alimentação", tipo="receita", natureza="extraordinario"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/rendimentos-recorrentes/novo",
            data={
                "titular_id": str(titular.id),
                "conta_id": str(conta.id),
                "tipo": "entrada",
                "categoria_id": str(categoria.id),
                "valor": "150.00",
                "dia_do_mes": "1",
                "descricao": "Subsídio de alimentação mensal",
            },
        )

    assert resposta.status_code in (200, 303)

    recorrentes = await recorrente_repo.listar_ativos(db_session)
    assert len(recorrentes) == 1
    assert recorrentes[0].conta_id == conta.id
    assert recorrentes[0].valor == Decimal("150.00")
    assert recorrentes[0].dia_do_mes == 1
    assert recorrentes[0].categoria_id == categoria.id


@pytest.mark.asyncio
async def test_post_rendimento_recorrente_novo_sem_conta_nao_falha_com_uuid_vazio(db_session):
    from ava.repositories import categoria_repo, recorrente_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    grupo = await categoria_repo.criar_grupo(db_session, nome="Rendimentos")
    categoria = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Salário", tipo="receita", natureza="extraordinario")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/rendimentos-recorrentes/novo",
            data={
                "titular_id": str(titular.id),
                "conta_id": "",
                "tipo": "entrada",
                "categoria_id": str(categoria.id),
                "valor": "1500.00",
                "dia_do_mes": "25",
                "descricao": "",
            },
        )

    assert resposta.status_code in (200, 303)

    recorrentes = await recorrente_repo.listar_ativos(db_session)
    assert len(recorrentes) == 1
    assert recorrentes[0].conta_id is None
    assert recorrentes[0].titular_id == titular.id


@pytest.mark.asyncio
async def test_home_serve_o_novo_layout_com_barra_lateral(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert 'href="/static/app.css' in resposta.text
    assert 'href="/patrimonio"' in resposta.text
    assert 'href="/alertas"' in resposta.text


@pytest.mark.asyncio
async def test_post_movimento_desfazer_apaga_e_devolve_a_movimentos(db_session):
    from ava.repositories import categoria_repo, conta_repo, linha_extrato_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Teste"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=11, nivel_extracao=0, dados_extraidos={}
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação Desfazer")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado Desfazer", tipo="despesa", natureza="variavel"
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id, data=date(2026, 7, 10), valor=Decimal("-8.50"),
        descricao="COMPRA CONTINENTE",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{linha.id}/despesa", data={"categoria_id": str(categoria.id)}
        )
    assert resposta.status_code == 200

    movimentos_da_conta = await movimento_repo.listar_por_conta(db_session, conta.id)
    assert len(movimentos_da_conta) == 1
    movimento_id = movimentos_da_conta[0].id

    async with _client_para(db_session) as client:
        resposta = await client.post(f"/movimentos/{movimento_id}/desfazer")

    assert resposta.status_code == 200
    assert "Desfeito" in resposta.text

    assert await movimento_repo.listar_por_conta(db_session, conta.id) == []
    linha_atualizada = await linha_extrato_repo.obter_por_id(db_session, linha.id)
    assert linha_atualizada.estado == "revisao_manual"

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")
    assert "COMPRA CONTINENTE" in resposta.text


@pytest.mark.asyncio
async def test_post_movimento_ficheiro_desfazer_reclassifica_via_movimentos(db_session):
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Teste"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    cat_original = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Restaurantes", tipo="despesa", natureza="variavel"
    )
    cat_nova = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel"
    )

    movimento = await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("42.00"),
        data=date(2026, 8, 15),
        origem="ficheiro",
        descricao="CONTINENTE BOM DIA",
        conta_id=conta.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("42.00"), categoria_id=cat_original.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        # 1. No dashboard, a despesa aparece na categoria original
        resp_cat = await client.get(f"/categorias/{cat_original.id}/movimentos?periodo=2026-08")
        assert "CONTINENTE BOM DIA" in resp_cat.text
        assert "Trocar categoria" in resp_cat.text

        # 2. Clicar em "Trocar categoria" chama /desfazer
        resposta = await client.post(f"/movimentos/{movimento.id}/desfazer")
        assert resposta.status_code == 200
        assert "Desfeito" in resposta.text

        # 3. O movimento não foi apagado da BD, mas já não tem categoria
        mov_bd = await movimento_repo.obter_por_id(db_session, movimento.id)
        assert mov_bd is not None
        assert mov_bd.linhas[0].categoria_id is None

        # 4. A despesa aparece em /movimentos (Movimentos por resolver / categorizar)
        resp_movimentos = await client.get("/movimentos")
        assert resp_movimentos.status_code == 200
        assert "CONTINENTE BOM DIA" in resp_movimentos.text
        assert f"/movimentos/manual/{movimento.id}/categorizar" in resp_movimentos.text

        # 5. O utilizador escolhe a nova categoria e categoriza
        resp_cat_nova = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={"categoria_id": str(cat_nova.id), "conta_id": str(conta.id)},
        )
        assert resp_cat_nova.status_code == 200

        # 6. A despesa agora pertence à nova categoria
        mov_bd_atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
        assert mov_bd_atualizado.linhas[0].categoria_id == cat_nova.id

        resp_cat_nova_movs = await client.get(f"/categorias/{cat_nova.id}/movimentos?periodo=2026-08")
        assert "CONTINENTE BOM DIA" in resp_cat_nova_movs.text


@pytest.mark.asyncio
async def test_post_movimento_desfazer_inexistente_404(db_session):
    import uuid

    async with _client_para(db_session) as client:
        resposta = await client.post(f"/movimentos/{uuid.uuid4()}/desfazer")

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_home_saldo_atual_mostra_conta_principal_e_liquidez_total(db_session):
    from ava.repositories import conta_repo, titular_repo, saldo_historico_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    c_bpi = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta BPI"
    )
    c_poupanca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="poupanca", nome="Poupança"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=c_bpi.id, data=date(2026, 8, 1), valor=Decimal("-750.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=c_poupanca.id, data=date(2026, 8, 1), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/?periodo=2026-08")

    assert resposta.status_code == 200
    # Saldo da conta à ordem principal (-750.00 €) em destaque
    assert "-750,00" in resposta.text
    # Liquidez total (-750 + 1000 = 250.00 €) no subtítulo
    assert "Liquidez total:" in resposta.text
    assert "250,00" in resposta.text


@pytest.mark.asyncio
async def test_get_trocar_categoria_form_retorna_html_com_categorias(db_session):
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta")
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    cat1 = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Restaurantes", tipo="despesa", natureza="variavel")
    cat2 = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel")

    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("18.50"), data=date(2026, 8, 10),
        origem="ficheiro", descricao="JANTAR", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("18.50"), categoria_id=cat1.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/movimentos/{movimento.id}/trocar-categoria-form?categoria_id={cat1.id}")

    assert resposta.status_code == 200
    assert "Supermercado" in resposta.text
    assert f'hx-post="/movimentos/{movimento.id}/trocar-categoria"' in resposta.text


@pytest.mark.asyncio
async def test_post_trocar_categoria_atualiza_categoria_do_movimento(db_session):
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta")
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    cat1 = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Restaurantes", tipo="despesa", natureza="variavel")
    cat2 = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Supermercado", tipo="despesa", natureza="variavel")

    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("35.00"), data=date(2026, 8, 10),
        origem="ficheiro", descricao="COMPRAS", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("35.00"), categoria_id=cat1.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/trocar-categoria",
            data={"nova_categoria_id": str(cat2.id)},
        )

    assert resposta.status_code == 200
    assert "Movido para" in resposta.text
    assert "Supermercado" in resposta.text

    mov_atualizado = await movimento_repo.obter_por_id(db_session, movimento.id)
    assert mov_atualizado.linhas[0].categoria_id == cat2.id


@pytest.mark.asyncio
async def test_get_linha_categoria_cancela_edicao_e_mostra_linha_normal(db_session):
    from ava.repositories import categoria_repo, conta_repo, movimento_repo, titular_repo
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta")
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    cat1 = await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Restaurantes", tipo="despesa", natureza="variavel")

    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("12.00"), data=date(2026, 8, 10),
        origem="ficheiro", descricao="ALMOCO", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("12.00"), categoria_id=cat1.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/movimentos/{movimento.id}/linha-categoria?categoria_id={cat1.id}")

    assert resposta.status_code == 200
    assert "ALMOCO" in resposta.text
    assert "Trocar categoria" in resposta.text



@pytest.mark.asyncio
async def test_movimentos_de_uma_conta_mostra_so_os_dela(db_session):
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Teste"
    )
    conta_outra = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Outra"
    )
    await db_session.flush()
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("42.00"), data=date(2026, 7, 10),
        origem="manual", descricao="Supermercado XYZ", conta_id=conta.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("42.00"), categoria_id=None)],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("99.00"), data=date(2026, 7, 11),
        origem="manual", descricao="Da Outra Conta", conta_id=conta_outra.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("99.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        # mes_ano explícito: sem filtros a rota assume o mês corrente (dashboard.py), e estes
        # movimentos são de julho/2026 — sem isto o teste dependeria da data em que corre.
        resposta = await client.get(f"/patrimonio/contas/{conta.id}", params={"mes_ano": "2026-07"})

    assert resposta.status_code == 200
    assert "Supermercado XYZ" in resposta.text
    assert "Conta Teste" in resposta.text
    assert "Da Outra Conta" not in resposta.text  # movimento da outra conta não deve aparecer


@pytest.mark.asyncio
async def test_movimentos_de_conta_filtra_por_busca_valor_e_data(db_session):
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Teste"
    )
    await db_session.flush()
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("50.00"), data=date(2026, 7, 5),
        origem="manual", descricao="Supermercado Continente", conta_id=conta.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("50.00"))],
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("8.00"), data=date(2026, 7, 10),
        origem="manual", descricao="Farmácia Central", conta_id=conta.id, registado_por=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("8.00"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}", params={"busca": "continente"})
    assert "Supermercado Continente" in resposta.text
    assert "Farmácia Central" not in resposta.text

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}", params={"valor_max": "10"})
    assert "Farmácia Central" in resposta.text
    assert "Supermercado Continente" not in resposta.text

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}", params={"busca": "inexistente"})
    assert "Sem movimentos a corresponder aos filtros" in resposta.text


@pytest.mark.asyncio
async def test_movimentos_de_conta_mostra_transferencia_com_nome_da_outra_conta(db_session):
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()
    conta_a_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta à Ordem"
    )
    conta_credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Mortgage & Loans"
    )
    await db_session.flush()
    await movimento_repo.criar_movimento(
        db_session,
        tipo="transferencia",
        valor=Decimal("457.33"),
        data=date(2026, 7, 25),
        origem="extrato",
        descricao="Amortização de capital",
        conta_id=conta_a_ordem.id,
        conta_destino_id=conta_credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("457.33"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta_a_ordem = await client.get(f"/patrimonio/contas/{conta_a_ordem.id}", params={"mes_ano": "2026-07"})
        resposta_credito = await client.get(f"/patrimonio/contas/{conta_credito.id}", params={"mes_ano": "2026-07"})

    # a mesma transferência aparece nas DUAS páginas de conta, cada uma mostrando o nome da OUTRA
    assert "Amortização de capital" in resposta_a_ordem.text
    assert "Mortgage & Loans" in resposta_a_ordem.text
    assert "Amortização de capital" in resposta_credito.text
    assert "Conta à Ordem" in resposta_credito.text

    # cor por lado: dinheiro sai da conta à ordem (vermelho), a dívida desce na conta de crédito
    # (verde) — a MESMA transferência, cor oposta consoante a conta que se está a ver.
    #
    # Ancorado ao cartão do valor (conta_movimentos.html) e não à página inteira: a barra lateral
    # de base.html tem um link de encerrar com !text-negative em TODAS as páginas, por isso um
    # `"text-negative" not in resposta.text` nunca mais poderia passar — passaria a testar o
    # layout em vez da cor da transferência.
    valor_negativo = 'cartao-registo-valor text-negative">'
    valor_positivo = 'cartao-registo-valor text-positive">'
    assert valor_negativo in resposta_a_ordem.text
    assert valor_positivo not in resposta_a_ordem.text
    assert valor_positivo in resposta_credito.text
    assert valor_negativo not in resposta_credito.text


@pytest.mark.asyncio
async def test_movimentos_de_conta_inexistente_404(db_session):
    import uuid

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{uuid.uuid4()}")

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_avaliacao_cria_observacao(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao",
            data={"data": "2026-03-12", "valor": "8400.00"},
        )

    assert resposta.status_code in (200, 303)
    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativo.id)
    assert len(historico) == 1
    assert historico[0].valor == Decimal("8400.00")
    assert historico[0].data == date(2026, 3, 12)
    assert historico[0].origem == "observado"


@pytest.mark.asyncio
async def test_post_avaliacao_na_mesma_data_substitui(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao",
            data={"data": "2026-03-12", "valor": "8400.00"},
        )
        await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao",
            data={"data": "2026-03-12", "valor": "8900.00"},
        )

    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativo.id)
    assert len(historico) == 1
    assert historico[0].valor == Decimal("8900.00")


@pytest.mark.asyncio
async def test_post_avaliacao_com_valor_invalido_nao_cria_nada(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao",
            data={"data": "2026-03-12", "valor": "abc"},
        )

    assert resposta.status_code in (200, 303)
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativo.id) == []


@pytest.mark.asyncio
async def test_post_avaliacao_com_data_futura_nao_cria_nada(db_session):
    # Uma data futura é tratada como entrada malformada: um erro de dedo (2062 em vez de 2026)
    # não pode meter um ponto no futuro na série de património (ver saldo_historico_repo).
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await db_session.commit()

    data_futura = (date.today() + timedelta(days=1)).isoformat()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao",
            data={"data": data_futura, "valor": "8400.00"},
        )

    assert resposta.status_code in (200, 303)
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativo.id) == []


@pytest.mark.asyncio
async def test_apagar_avaliacao(db_session):
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    avaliacao = await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 3, 12), valor=Decimal("8400.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao/{avaliacao.id}/apagar"
        )

    assert resposta.status_code in (200, 303)
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativo.id) == []


@pytest.mark.asyncio
async def test_apagar_avaliacao_de_outro_ativo_devolve_404_e_nao_apaga(db_session):
    # apagar_avaliacao_ativo apagava por avaliacao_id sem confirmar que pertence a ativo_id do
    # URL — o URL de QUALQUER ativo conseguia apagar a avaliação de OUTRO. Um facto observado
    # não pode desaparecer sem essa verificação.
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo_a = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo="carro")
    ativo_b = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Vespa", tipo="mota")
    avaliacao_de_b = await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo_b.id, data=date(2026, 3, 12), valor=Decimal("2000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo_a.id}/avaliacao/{avaliacao_de_b.id}/apagar"
        )

    assert resposta.status_code == 404
    restantes = await ativo_valor_repo.listar_por_ativo(db_session, ativo_b.id)
    assert len(restantes) == 1
    assert restantes[0].id == avaliacao_de_b.id


@pytest.mark.asyncio
async def test_apagar_avaliacao_inexistente_devolve_404(db_session):
    import uuid

    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo="carro")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/avaliacao/{uuid.uuid4()}/apagar"
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_taxa_anual_grava_a_taxa_propria_do_ativo(db_session):
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Clássico", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/taxa", data={"taxa_anual": "5"}
        )

    assert resposta.status_code in (200, 303)
    await db_session.refresh(ativo)
    # O formulário recebe percentagem (5) e grava fração (0.05).
    assert ativo.taxa_anual == Decimal("0.0500")


@pytest.mark.asyncio
async def test_post_taxa_anual_vazia_volta_a_usar_a_omissao_do_tipo(db_session):
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro",
        taxa_anual=Decimal("0.05"),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(f"/patrimonio/ativos/{ativo.id}/taxa", data={"taxa_anual": ""})

    await db_session.refresh(ativo)
    assert ativo.taxa_anual is None


@pytest.mark.asyncio
async def test_post_taxa_anual_menos_cem_por_cento_e_ignorada_em_vez_de_trancar_a_pagina(db_session):
    # -100% (ou menos) torna a base da potência composta não positiva: valorizacao.projetar
    # levanta InvalidOperation em /, /patrimonio, /configuracoes/patrimonio E nesta própria
    # página — o único sítio com o formulário para corrigir o erro. Tem de ser recusada antes de
    # gravar, não descoberta só quando a página seguinte rebenta.
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Clássico", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/taxa", data={"taxa_anual": "-150"}
        )

    assert resposta.status_code in (200, 303)
    await db_session.refresh(ativo)
    assert ativo.taxa_anual is None

    # A própria página do ativo continua acessível — não há registo nenhum a trancá-la.
    async with _client_para(db_session) as client:
        resposta_detalhe = await client.get(f"/patrimonio/ativos/{ativo.id}")
    assert resposta_detalhe.status_code == 200


@pytest.mark.asyncio
async def test_post_taxa_anual_acima_de_mil_por_cento_e_ignorada_sem_overflow(db_session):
    # Acima de ~1000%, Numeric(5,4) não consegue representar a fração e o commit rebenta com
    # "numeric field overflow". Tem de ser recusada em vez de deixar a exceção subir.
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Clássico", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/taxa", data={"taxa_anual": "1500"}
        )

    assert resposta.status_code in (200, 303)
    await db_session.refresh(ativo)
    assert ativo.taxa_anual is None


@pytest.mark.asyncio
async def test_post_taxa_anual_dentro_do_intervalo_extremo_e_gravada(db_session):
    # Os limites em si (-99% e +999%) são válidos e devem ser gravados — só o que está FORA do
    # intervalo é recusado.
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Clássico", tipo="carro"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/patrimonio/ativos/{ativo.id}/taxa", data={"taxa_anual": "-99"}
        )

    assert resposta.status_code in (200, 303)
    await db_session.refresh(ativo)
    assert ativo.taxa_anual == Decimal("-0.9900")


@pytest.mark.asyncio
async def test_ativo_detalhe_com_avaliacao_retorna_200(db_session):
    # Defeito apanhado numa ronda de correção anterior: a rota nunca fazia GET nos testes, por
    # isso um 500 (Jinja UndefinedError em total_gasto_geral) sobreviveu sem ser detetado. Este
    # teste existe especificamente para impedir que a página volte a rebentar em silêncio.
    from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date.today(), valor=Decimal("8000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{ativo.id}")

    assert resposta.status_code == 200
    assert "Corsa" in resposta.text


@pytest.mark.asyncio
async def test_ativo_detalhe_sem_despesas_nem_avaliacao_retorna_200(db_session):
    # O caso mais provável de rebentar por divisão por zero ou lista vazia: um ativo acabado de
    # criar, sem nenhum abastecimento, despesa ou avaliação associada.
    from ava.repositories import ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Mota Nova", tipo="mota"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{ativo.id}")

    assert resposta.status_code == 200
    assert "Mota Nova" in resposta.text


@pytest.mark.asyncio
async def test_ativo_detalhe_mostra_despesa_associada(db_session):
    from ava.repositories import ativo_repo, categoria_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Seguros Teste")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Seguro Auto", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()
    # Sem leitura_odometro: não é abastecimento, é uma das "outras despesas" do ativo.
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("120.00"),
        data=date(2026, 4, 1),
        origem="manual",
        descricao="Seguro anual",
        linhas=[
            movimento_repo.LinhaNova(
                valor=Decimal("120.00"), categoria_id=categoria.id, ativo_id=ativo.id
            )
        ],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{ativo.id}")

    assert resposta.status_code == 200
    assert "Seguro anual" in resposta.text
    assert "120,00" in resposta.text


@pytest.mark.asyncio
async def test_alertas_junta_revisao_prazos_e_falhas(db_session):
    await documento_repo.criar_documento(
        db_session, paperless_document_id=901, nivel_extracao=1, dados_extraidos={},
        estado_validacao="revisao_manual",
    )
    await obrigacao_repo.criar_obrigacao(
        db_session, tipo="imposto", descricao="IUC", data_limite=date.today() + timedelta(days=5),
        origem="manual",
    )
    item = await fila_repo.criar_item(db_session, texto_ocr="x")
    await fila_repo.marcar_erro(db_session, item.id, "erro de teste")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/alertas")

    assert resposta.status_code == 200
    assert "IUC" in resposta.text
    assert "erro de teste" in resposta.text


async def _movimento_de_despesa(db_session, *, titular, conta, descricao="GALP AREAS 999999"):
    # Cria um movimento de saída já categorizado, como o faria a reconciliação automática.
    from ava.repositories import categoria_repo, movimento_repo

    grupo = await categoria_repo.criar_grupo(db_session, nome=f"G {descricao}")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=f"C {descricao}", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()
    return await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("60.00"), data=date(2026, 8, 1),
        origem="extrato", descricao=descricao, conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("60.00"), categoria_id=categoria.id)],
    )


@pytest.mark.asyncio
async def test_post_ativo_do_movimento_atribui_o_bem(db_session):
    # O caso que motiva a tarefa: um movimento criado pela reconciliação automática (sem ativo)
    # tem de poder receber o bem depois.
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    audi = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=conta)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ativo", data={"ativo_id": str(audi.id)}
        )

    assert resposta.status_code in (200, 303)
    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.ativo_id == audi.id for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_post_ativo_do_movimento_com_valor_vazio_desatribui(db_session):
    # Desatribuir é como se corrige um engano — tem de ser possível.
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    audi = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=conta)
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(f"/movimentos/{movimento.id}/ativo", data={"ativo_id": str(audi.id)})
        await client.post(f"/movimentos/{movimento.id}/ativo", data={"ativo_id": ""})

    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.ativo_id is None for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_post_ativo_do_movimento_recusa_ativo_inexistente(db_session):
    # Não se grava uma referência órfã.
    import uuid as _uuid

    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=conta)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ativo", data={"ativo_id": str(_uuid.uuid4())}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_ativo_do_movimento_recusa_ativo_id_malformado(db_session):
    # Um ativo_id que nem sequer é um UUID válido deve dar o mesmo 404 que um ativo
    # inexistente, não um 500 por ValueError não apanhado no uuid.UUID(...).
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=conta)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ativo", data={"ativo_id": "nao-e-um-uuid"}
        )

    assert resposta.status_code == 404
    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.ativo_id is None for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_post_ativo_do_movimento_recusa_transferencia(db_session):
    # Uma transferência não tem bem associado.
    from ava.repositories import ativo_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito"
    )
    audi = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("450.00"), data=date(2026, 8, 3),
        origem="extrato", descricao="Amortização", conta_id=ordem.id,
        conta_destino_id=credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("450.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ativo", data={"ativo_id": str(audi.id)}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_credito_do_movimento_liga_a_divida(db_session):
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans",
    )
    movimento = await _movimento_de_despesa(
        db_session, titular=titular, conta=ordem, descricao="JUROS DE EMPRESTIMO - 165-008"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )

    assert resposta.status_code in (200, 303)
    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.conta_relacionada_id == credito.id for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_post_credito_com_valor_vazio_desliga(db_session):
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=ordem)
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )
        await client.post(
            f"/movimentos/{movimento.id}/credito", data={"conta_relacionada_id": ""}
        )

    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.conta_relacionada_id is None for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_post_credito_recusa_conta_que_nao_e_divida(db_session):
    # Ligar uma despesa a uma conta à ordem não significa nada.
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=ordem)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": str(ordem.id)},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_credito_recusa_conta_inexistente(db_session):
    # Um conta_relacionada_id bem formado mas que não corresponde a nenhuma conta também dá 404,
    # não só o UUID malformado (espelha test_post_ativo_do_movimento_recusa_ativo_inexistente).
    import uuid as _uuid

    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=ordem)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": str(_uuid.uuid4())},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_credito_recusa_movimento_inexistente(db_session):
    import uuid as _uuid

    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{_uuid.uuid4()}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_credito_recusa_movimento_de_transferencia(db_session):
    # Uma transferência não pertence a um crédito — o seletor nem aparece nesse caso.
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito"
    )
    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("450.00"), data=date(2026, 8, 3),
        origem="extrato", descricao="Amortização", conta_id=ordem.id,
        conta_destino_id=credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("450.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_post_credito_recusa_conta_relacionada_id_malformado(db_session):
    # Um conta_relacionada_id que nem sequer é um UUID válido deve dar o mesmo 404 que uma
    # conta inexistente, não um 500 por ValueError não apanhado no uuid.UUID(...).
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    movimento = await _movimento_de_despesa(db_session, titular=titular, conta=ordem)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/credito",
            data={"conta_relacionada_id": "nao-e-um-uuid"},
        )

    assert resposta.status_code == 404
    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.conta_relacionada_id is None for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_categorizar_movimento_manual_grava_o_ativo_escolhido(db_session):
    # O seletor de ativo aparece em /movimentos também nas entradas manuais (movimentos.html não
    # o esconde com o guard is_manual) — sem a rota aceitar `ativo_id`, a escolha era descartada
    # em silêncio.
    from sqlalchemy import select

    from ava.models.movimento_linha import MovimentoLinha
    from ava.repositories import ativo_repo, categoria_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    audi = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro")
    grupo = await categoria_repo.criar_grupo(db_session, nome="G Fuel Type")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Fuel Type", tipo="despesa", natureza="variavel"
    )
    await db_session.flush()
    movimento = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("40.00"), data=date(2026, 8, 5),
        origem="manual", descricao="GALP", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("40.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/manual/{movimento.id}/categorizar",
            data={
                "categoria_id": str(categoria.id),
                "conta_id": str(conta.id),
                "ativo_id": str(audi.id),
            },
        )

    assert resposta.status_code == 200
    resultado = await db_session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento.id)
    )
    assert all(linha.ativo_id == audi.id for linha in resultado.scalars().all())


@pytest.mark.asyncio
async def test_conta_movimentos_mostra_seletor_de_ativo_nas_despesas(db_session):
    from ava.repositories import ativo_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito"
    )
    await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro")
    await _movimento_de_despesa(db_session, titular=titular, conta=conta)
    # Uma transferência (ex. amortização de crédito) não tem bem associado — o seletor não pode
    # aparecer aqui, senão submete-lo leva a um 404 (ver POST /movimentos/{id}/ativo, que recusa
    # movimentos que não sejam do tipo "saida").
    await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("450.00"), data=date(2026, 8, 3),
        origem="extrato", descricao="Amortização", conta_id=conta.id,
        conta_destino_id=credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("450.00"), categoria_id=None)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(
            f"/patrimonio/contas/{conta.id}", params={"mes_ano": "2026-08"}
        )

    assert resposta.status_code == 200
    assert 'name="ativo_id"' in resposta.text
    assert "City Hatchback 1.2" in resposta.text
    # Só a despesa tem seletor de ativo — a transferência, não.
    assert resposta.text.count('name="ativo_id"') == 1


@pytest.mark.asyncio
async def test_historico_de_conta_usa_cartao_de_registo_nao_tabela(db_session):
    from ava.repositories import categoria_repo, conta_repo, titular_repo
    from tests.fabricas import criar_movimento

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    grupo = await categoria_repo.criar_grupo(db_session, nome="Alimentação")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Compras", tipo="despesa", natureza="variavel"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="30.00",
        data=date(2026, 8, 5), categoria_id=categoria.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}")

    assert resposta.status_code == 200
    assert "30,00" in resposta.text
    assert 'class="cartao-registo"' in resposta.text
    assert "<table" not in resposta.text


@pytest.mark.asyncio
async def test_ativo_detalhe_mostra_valor_liquido(db_session):
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=hipoteca.id, data=date.today(), valor=Decimal("151970.07")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert resposta.status_code == 200
    assert "400.000,00" in resposta.text   # bruto
    assert "151.970,07" in resposta.text   # em dívida
    assert "248.029,93" in resposta.text   # líquido


@pytest.mark.asyncio
async def test_ativo_detalhe_valor_liquido_reflete_amortizacao_depois_da_ancora(db_session):
    # REGRESSAO (revisao final, achado 5): a pagina do bem lia obter_saldo_mais_recente (a
    # ancora crua) em vez do saldo DERIVADO que /patrimonio ja usa -- no mes entre uma
    # amortizacao registada e o extrato seguinte, as duas paginas mostravam valores liquidos
    # diferentes do MESMO bem.
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)
    from tests.fabricas import criar_transferencia

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=hipoteca.id, data=date(2026, 7, 3), valor=Decimal("152433.26")
    )
    # Amortizacao registada DEPOIS da ancora -- ainda sem extrato novo a confirma-la.
    await criar_transferencia(
        db_session, valor="463.19", data=date(2026, 8, 3), origem=ordem, destino=hipoteca, titular=titular
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert resposta.status_code == 200
    assert "151.970,07" in resposta.text        # em dívida, JÁ com a amortização descontada
    assert "152.433,26" not in resposta.text    # a âncora crua, sem os movimentos desde ela


@pytest.mark.asyncio
async def test_ativo_detalhe_soma_duas_dividas_do_mesmo_bem(db_session):
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    for nome, valor in (("Hipoteca", "150000.00"), ("Obras", "10000.00")):
        conta = await conta_repo.criar_conta(
            db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
            nome=nome, ativo_id=casa.id,
        )
        await saldo_historico_repo.registar_saldo(
            db_session, conta_id=conta.id, data=date.today(), valor=Decimal(valor)
        )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert "240.000,00" in resposta.text  # 400.000 − 160.000


@pytest.mark.asyncio
async def test_ativo_detalhe_liquido_negativo_mostra_se_como_negativo(db_session):
    # Um carro que deprecia mais depressa do que o credito amortiza vale menos do que se deve
    # por ele. Verdade desconfortavel e util, nao erro a esconder (spec §3).
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    carro = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=carro.id, data=date.today(), valor=Decimal("2000.00")
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BBVA", tipo="divida",
        nome="Crédito Automóvel", ativo_id=carro.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=credito.id, data=date.today(), valor=Decimal("3500.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{carro.id}")

    assert resposta.status_code == 200
    assert "-1.500,00" in resposta.text


@pytest.mark.asyncio
async def test_ativo_detalhe_sem_avaliacao_nao_mostra_liquido(db_session):
    # Nao se subtrai uma divida conhecida de um valor desconhecido (spec §3).
    from ava.repositories import conta_repo, saldo_historico_repo, ativo_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    carro = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BBVA", tipo="divida",
        nome="Crédito Automóvel", ativo_id=carro.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=credito.id, data=date.today(), valor=Decimal("3500.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{carro.id}")

    assert resposta.status_code == 200
    assert "Sem avaliação" in resposta.text
    assert "-3.500,00" not in resposta.text


@pytest.mark.asyncio
async def test_custo_do_bem_inclui_juros_do_credito_ligado(db_session):
    # O objetivo da spec: marcar os juros como pertencendo ao credito faz com que contem no
    # custo do bem que esse credito financiou.
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    juros = await _movimento_de_despesa(
        db_session, titular=titular, conta=ordem, descricao="JUROS DE EMPRESTIMO - 165-008"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            f"/movimentos/{juros.id}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert resposta.status_code == 200
    # _movimento_de_despesa cria uma despesa de 60,00.
    assert "60,00" in resposta.text
    assert "JUROS DE EMPRESTIMO" in resposta.text


@pytest.mark.asyncio
async def test_custo_do_bem_nao_conta_a_mesma_despesa_duas_vezes(db_session):
    # Uma linha com ativo_id E conta_relacionada_id do mesmo bem entra uma so vez (spec §4).
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    despesa = await _movimento_de_despesa(db_session, titular=titular, conta=ordem)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta_ativo = await client.post(
            f"/movimentos/{despesa.id}/ativo", data={"ativo_id": str(casa.id)}
        )
        resposta_credito = await client.post(
            f"/movimentos/{despesa.id}/credito",
            data={"conta_relacionada_id": str(credito.id)},
        )
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    # As duas ligações de setup têm de ter gravado, senão o teste passa por a despesa nem sequer
    # aparecer (falso positivo).
    assert resposta_ativo.status_code == 200
    assert resposta_credito.status_code == 200
    # A despesa está lá exatamente uma vez: 60,00, não 120,00 (dupla contagem) nem ausente.
    assert "60,00" in resposta.text
    assert "120,00" not in resposta.text


@pytest.mark.asyncio
async def test_custo_do_bem_ignora_despesa_de_credito_de_outro_bem(db_session):
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    carro = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="City Hatchback 1.2", tipo="carro"
    )
    credito_carro = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BBVA", tipo="divida",
        nome="Crédito Automóvel", ativo_id=carro.id,
    )
    juros = await _movimento_de_despesa(
        db_session, titular=titular, conta=ordem, descricao="JUROS AUTOMOVEL"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            f"/movimentos/{juros.id}/credito",
            data={"conta_relacionada_id": str(credito_carro.id)},
        )
        resposta_casa = await client.get(f"/patrimonio/ativos/{casa.id}")
        resposta_carro = await client.get(f"/patrimonio/ativos/{carro.id}")

    assert "JUROS AUTOMOVEL" not in resposta_casa.text
    assert "JUROS AUTOMOVEL" in resposta_carro.text


@pytest.mark.asyncio
async def test_custo_do_bem_nao_conta_o_capital_amortizado(db_session):
    # Amortizar nao e gastar: o dinheiro nao desapareceu, mudou de sitio no balanco. A
    # amortizacao e um `movimento` de tipo `transferencia` e nao pode entrar no custo (spec §4).
    from ava.repositories import ativo_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    credito = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    # Amortização: transferência da conta à ordem para o crédito, com a linha a apontar para
    # o crédito — exatamente a forma que teria se fosse marcada como pertencendo a ele.
    amortizacao = await movimento_repo.criar_movimento(
        db_session, tipo="transferencia", valor=Decimal("450.00"), data=date(2026, 8, 3),
        origem="extrato", descricao="AMORTIZACAO DE CAPITAL", conta_id=ordem.id,
        conta_destino_id=credito.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("450.00"), categoria_id=None)],
    )
    await db_session.flush()
    for linha in amortizacao.linhas:
        linha.conta_relacionada_id = credito.id
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert resposta.status_code == 200
    assert "450,00" not in resposta.text
    assert "AMORTIZACAO DE CAPITAL" not in resposta.text


@pytest.mark.asyncio
async def test_custo_do_bem_nao_conta_um_rendimento_atribuido_ao_bem(db_session):
    # Um rendimento nao e um custo. O caso e alcancavel: resolver_como_rendimento e
    # categorizar_movimento_manual gravam ativo_id sem verificar o tipo do movimento, por isso
    # uma entrada pode ficar marcada com um bem. Antes do filtro `saida` ela somava no
    # "Total Gasto" da pagina do bem, o que era simplesmente errado.
    from ava.repositories import ativo_repo, conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("175.00"), data=date(2026, 8, 1),
        origem="extrato", descricao="REEMBOLSO SEGURO CASA", conta_id=ordem.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("175.00"), ativo_id=casa.id)],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert resposta.status_code == 200
    assert "175,00" not in resposta.text
    assert "REEMBOLSO SEGURO CASA" not in resposta.text


@pytest.mark.asyncio
async def test_ligar_divida_a_bem_nao_altera_o_patrimonio(db_session):
    # REGRESSÃO de §3.1: a divida ja esta subtraida em patrimonio_financeiro. Se a ligacao
    # mexesse nas formulas, a hipoteca contava em dobro.
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=ordem.id, data=date.today(), valor=Decimal("5000.00")
    )
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Hipoteca"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=hipoteca.id, data=date.today(), valor=Decimal("150000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        antes = await client.get("/patrimonio")
        await client.post(
            f"/configuracoes/contas/{hipoteca.id}/ativo", data={"ativo_id": str(casa.id)}
        )
        depois = await client.get("/patrimonio")

    # financeiro = 5.000 − 150.000 = −145.000; total = −145.000 + 400.000 = 255.000
    for html in (antes.text, depois.text):
        assert "-145.000,00" in html
        assert "255.000,00" in html


@pytest.mark.asyncio
async def test_ativo_detalhe_ignora_divida_de_conta_apagada(db_session):
    # REGRESSAO (revisão do ramo, Achado 1, Porta A): apagar uma conta (desativar_conta) só põe
    # `ativo=False` — não limpa `ativo_id`. Sem filtrar por `ativo` em listar_dividas_do_ativo, a
    # página do bem continuava a subtrair um saldo que /patrimonio já tinha deixado de contar.
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=hipoteca.id, data=date.today(), valor=Decimal("151970.07")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        antes = await client.get(f"/patrimonio/ativos/{casa.id}")
        assert "151.970,07" in antes.text
        assert "248.029,93" in antes.text

        resposta_apagar = await client.post(f"/configuracoes/contas/{hipoteca.id}/apagar")
        assert resposta_apagar.status_code == 303  # redirect para /configuracoes/patrimonio

        depois = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert depois.status_code == 200
    assert "151.970,07" not in depois.text
    assert "248.029,93" not in depois.text
    assert "Em dívida" not in depois.text
    # sem dívida ligada, o valor líquido é o valor bruto do bem — que continua visível.
    assert "400.000,00" in depois.text


@pytest.mark.asyncio
async def test_ativo_detalhe_ignora_divida_de_conta_reclassificada(db_session):
    # REGRESSAO (revisão do ramo, Achado 1, Porta B): editar uma conta (atualizar_conta) escreve
    # `tipo` mas também não toca em `ativo_id`. Sem filtrar por `tipo` em listar_dividas_do_ativo,
    # reclassificar uma dívida ligada para "a_ordem" fazia o mesmo saldo contar como bem em
    # /patrimonio e continuar, ao mesmo tempo, a ser subtraído na página do bem.
    from ava.repositories import (ativo_repo, ativo_valor_repo, conta_repo,
                                  saldo_historico_repo, titular_repo)

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=casa.id, data=date.today(), valor=Decimal("400000.00")
    )
    hipoteca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=hipoteca.id, data=date.today(), valor=Decimal("151970.07")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        antes = await client.get(f"/patrimonio/ativos/{casa.id}")
        assert "151.970,07" in antes.text
        assert "248.029,93" in antes.text

        resposta_editar = await client.post(
            f"/configuracoes/contas/{hipoteca.id}/editar",
            data={
                "titular_id": str(titular.id),
                "nome": "Mortgage & Loans",
                "instituicao": "BPI",
                "tipo": "a_ordem",
            },
        )
        assert resposta_editar.status_code == 303  # redirect para /configuracoes/patrimonio

        depois = await client.get(f"/patrimonio/ativos/{casa.id}")

    assert depois.status_code == 200
    assert "151.970,07" not in depois.text
    assert "248.029,93" not in depois.text
    assert "Em dívida" not in depois.text
    assert "400.000,00" in depois.text


@pytest.mark.asyncio
async def test_registo_get_usa_a_navegacao_partilhada_da_app(db_session):
    # O registo rápido era uma página standalone (<!DOCTYPE html> próprio, sem sidebar/barra
    # inferior) — passou a estender base.html para se sentir parte da app em vez de um destino à
    # parte. Confirma que a navegação partilhada (sidebar + barra inferior) está presente, e que
    # o formulário original continua completo (mesmos campos, mesma rota).
    async with _client_para(db_session) as client:
        resposta = await client.get("/registo")

    assert resposta.status_code == 200
    assert 'class="sidebar"' in resposta.text
    assert 'class="bottom-tab-bar"' in resposta.text
    assert 'action="/registo"' in resposta.text
    assert 'name="conta_id"' in resposta.text
    assert 'name="tipo"' in resposta.text
    assert 'name="categoria_id"' in resposta.text
    assert 'name="valor"' in resposta.text
    assert 'name="descricao"' in resposta.text
    assert 'name="data"' in resposta.text


@pytest.mark.asyncio
async def test_registo_get_so_lista_cartoes_de_refeicao(db_session):
    # Achado de 2026-08-20: a conta à ordem e as poupanças já chegam pelo extrato/ficheiro --
    # oferecê-las aqui convidava a um registo manual redundante. O cartão de refeição é o único
    # tipo sem extrato nenhum, por isso é o único que este formulário continua a oferecer.
    from ava.repositories import conta_repo
    from tests.fabricas import criar_titular_e_conta

    titular, _ = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="poupanca", nome="Poupança"
    )
    cartao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred",
        tipo="cartao_refeicao", nome="Cartão Refeição",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/registo")

    assert resposta.status_code == 200
    assert f'value="{cartao.id}"' in resposta.text
    assert "Ordem" not in resposta.text
    assert "Poupança" not in resposta.text


@pytest.mark.asyncio
async def test_registo_get_so_lista_categorias_pagaveis_com_cartao_de_refeicao(db_session):
    # Achado de 2026-08-20: um cartão de refeição só pode legalmente ser usado em supermercado,
    # restaurante e café (spec 2026-08-08 §1.1) -- oferecer as outras categorias no formulário
    # deixava escolher uma categoria que a despesa não podia ter tido.
    from ava.financas.categorias_iniciais import semear_categorias

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/registo")

    assert resposta.status_code == 200
    assert "Supermercado" in resposta.text
    assert "Restaurantes" in resposta.text
    assert "Café" in resposta.text
    # Categorias de outros grupos (Transportes, Habitação) não pagáveis com o cartão.
    assert "Fuel Type" not in resposta.text
    assert "Decoração" not in resposta.text
    # O grupo "Alimentação" sobrevive (tem categorias elegíveis); um grupo sem nenhuma
    # (ex. "Transportes") não deve aparecer nem vazio.
    assert '<optgroup label="Alimentação">' in resposta.text
    assert '<optgroup label="Transportes">' not in resposta.text


@pytest.mark.asyncio
async def test_registo_post_cria_o_movimento(db_session):
    # REGRESSAO: a rota usava `conta_final_id`, que nunca era definido (a variavel chama-se
    # `conta_id`), e levantava NameError. O formulario de registo nao funcionava de todo.
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    _, cartao = await criar_titular_e_conta(db_session, tipo="cartao_refeicao", nome="Cartão")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "12.34", "descricao": "Cafe",
                "conta_id": str(cartao.id),
            },
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Cafe"))
    movimento = resultado.scalar_one()
    assert movimento.valor == Decimal("12.34")
    assert movimento.data == date.today()


@pytest.mark.asyncio
async def test_registo_post_aceita_data_explicita(db_session):
    # Sem data real o casamento com as linhas de extrato seria adivinhacao (spec §5).
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    _, cartao = await criar_titular_e_conta(db_session, tipo="cartao_refeicao", nome="Cartão")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "9.99", "descricao": "Talao", "data": "2026-07-15",
                "conta_id": str(cartao.id),
            },
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Talao"))
    assert resultado.scalar_one().data == date(2026, 7, 15)


@pytest.mark.asyncio
async def test_registo_post_recusa_data_futura(db_session):
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session)
    await db_session.commit()

    amanha = (date.today() + timedelta(days=1)).isoformat()
    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={"tipo": "despesa", "valor": "5.00", "descricao": "Futuro", "data": amanha},
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Futuro"))
    assert resultado.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_registo_post_recusa_valor_nao_numerico(db_session):
    # `valor` passa de float a str (dinheiro em float e contra a regra do projeto). Um valor
    # que nao e numero devolve mensagem, nao 500.
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo", data={"tipo": "despesa", "valor": "abc", "descricao": "Mau"}
        )

    assert resposta.status_code == 303


@pytest.mark.asyncio
async def test_registo_post_nao_altera_a_ancora(db_session):
    # REGRESSAO de §7.1: a rota subtraia cada despesa ao valor da ancora mais recente,
    # destruindo o que o banco tinha declarado. Uma ancora nunca se muta.
    from ava.repositories import saldo_historico_repo
    from tests.fabricas import criar_titular_e_conta

    _, conta = await criar_titular_e_conta(db_session)
    _, cartao = await criar_titular_e_conta(db_session, tipo="cartao_refeicao", nome="Cartão")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            "/registo",
            data={"tipo": "despesa", "valor": "50.00", "descricao": "X", "conta_id": str(cartao.id)},
        )

    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    await db_session.refresh(ancora)
    assert ancora.valor == Decimal("1000.00")


@pytest.mark.asyncio
async def test_registo_post_honra_conta_id_do_cartao_de_refeicao(db_session):
    # REGRESSAO CRITICA (revisao final, achado 1): a rota ignorava por completo o `conta_id` do
    # formulario e debitava SEMPRE a conta a ordem -- inclusive quando o botao "Cartao de
    # refeicao" da home apontava para /registo?conta_id=<cartao>. O cartao nunca tem extrato
    # (spec §1.1), por isso o movimento nunca casava e ficava para sempre por confirmar.
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from ava.repositories import conta_repo, titular_repo
    from tests.fabricas import criar_titular_e_conta

    titular, _conta_ordem = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    cartao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred",
        tipo="cartao_refeicao", nome="Cartão Refeição",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "8.50", "descricao": "Almoço",
                "conta_id": str(cartao.id),
            },
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Almoço"))
    movimento = resultado.scalar_one()
    assert movimento.conta_id == cartao.id


@pytest.mark.asyncio
async def test_registo_post_sem_conta_id_e_recusado(db_session):
    # Achado de 2026-08-20: /registo passou a ser só para cartões de refeição, e uma casa pode
    # ter mais de um (um por titular) -- já não há uma conta à ordem única e óbvia para cair como
    # recurso. Sem escolha explícita, a rota recusa em vez de adivinhar a quem pertence a despesa.
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session, tipo="cartao_refeicao", nome="Cartão")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo", data={"tipo": "despesa", "valor": "8.50", "descricao": "Sem conta"}
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Sem conta"))
    assert resultado.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_registo_post_recusa_conta_que_nao_e_cartao_de_refeicao(db_session):
    # Achado de 2026-08-20: a conta à ordem já chega pelo extrato/ficheiro -- registá-la aqui à
    # mão duplicaria o trabalho quando o banco confirmar. Uma conta_id real mas do tipo errado
    # (não só uma inexistente) tem de ser recusada da mesma forma.
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    _, conta_ordem = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "8.50", "descricao": "Errado",
                "conta_id": str(conta_ordem.id),
            },
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Errado"))
    assert resultado.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_registo_post_recusa_conta_id_desconhecida(db_session):
    # Um conta_id bem formado mas que não corresponde a nenhuma conta ativa é recusado -- não
    # cai em silêncio na conta à ordem, que era exatamente a falha original.
    import uuid as _uuid
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "8.50", "descricao": "Fantasma",
                "conta_id": str(_uuid.uuid4()),
            },
        )

    assert resposta.status_code == 303
    resultado = await db_session.execute(select(Movimento).where(Movimento.descricao == "Fantasma"))
    assert resultado.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_registo_post_falha_nao_mostra_mensagem_em_verde(db_session):
    # REGRESSAO (re-revisao, achado 2): a heuristica de cor decidia por palavras ('inválido' ou
    # 'erro') presentes na mensagem. "Conta inválida." (género feminino) e "A data não pode ser
    # futura." não batem em nenhuma das duas, e caíam em text-positive -- o utilizador via VERDE e
    # nenhum movimento era criado. Agora só o prefixo do caminho de sucesso ("Registado com
    # sucesso:") conta como positivo; tudo o resto -- incluindo mensagens que não contêm nenhuma
    # das duas palavras -- é negativo. Critério escolhido: ausência da classe positiva (mais
    # simples e legível aqui do que afirmar a presença da negativa, embora a segunda também se
    # verifique, e fique confirmada no teste de contraste abaixo).
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={"tipo": "despesa", "valor": "abc", "descricao": "Mau"},
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    assert "text-positive" not in resposta.text
    assert "text-negative" in resposta.text


@pytest.mark.asyncio
async def test_registo_post_sucesso_mostra_mensagem_a_verde(db_session):
    # Contraste com o teste acima: só o caminho de sucesso (que começa por "Registado com
    # sucesso:") continua a cair em text-positive -- prova que o critério novo discrimina os dois
    # casos, e não ficou sempre negativo por acidente.
    from tests.fabricas import criar_titular_e_conta

    _, cartao = await criar_titular_e_conta(db_session, tipo="cartao_refeicao", nome="Cartão")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/registo",
            data={
                "tipo": "despesa", "valor": "12.34", "descricao": "Café",
                "conta_id": str(cartao.id),
            },
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    assert "text-positive" in resposta.text
    assert "text-negative" not in resposta.text


@pytest.mark.asyncio
async def test_home_mostra_a_margem_estrutural_sem_contar_adiantamentos(db_session):
    # O bug de origem: um adiantamento de cartão em "Outros rendimentos / Outros" era somado ao
    # salário porque o nome do grupo continha "rendimento". O controlo positivo é o salário —
    # sem ele, uma página que não mostrasse número nenhum passava neste teste.
    #
    # CORREÇÃO (revisão pós-implementação): a versão original deste teste usava a fábrica
    # `criar_categoria`, que cria sempre um grupo novo chamado "Grupo N" — nunca reproduzia o
    # nome real do grupo onde o bug vivia em produção ("Outros rendimentos"), pelo que a condição
    # do código antigo (`"rendimento" in nome_grupo.lower()`) nunca disparava contra este teste.
    # Também as duas primeiras asserções de texto eram satisfeitas pela secção "Rendimentos por
    # fonte" (lista sempre TODOS os rendimentos, bug ou não) e "Margem Estrutural" já era o rótulo
    # do bloco antigo "Visão Estrutural" — nenhuma das três provava nada sobre a margem. Por isso:
    # (a) o grupo do adiantamento é criado explicitamente com o nome "Outros rendimentos", como em
    # produção; (b) a asserção decisiva passa a ser o valor de `margem.margem` (que a página
    # mostra com sinal, ex. "+1.000,00 €") — com o bug, o adiantamento entrava na soma e a margem
    # seria "+1.500,00 €" em vez de "+1.000,00 €".
    from datetime import date

    from ava.repositories import categoria_repo
    from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta

    hoje = date.today()
    titular, conta = await criar_titular_e_conta(db_session)
    salario = await criar_categoria(
        db_session, nome="Salário", tipo="receita", natureza="recorrente"
    )
    grupo_outros_rendimentos = await categoria_repo.criar_grupo(db_session, nome="Outros rendimentos")
    outros = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_outros_rendimentos.id, nome="Outros",
        tipo="receita", natureza="extraordinario",
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="1000.00",
        data=hoje, categoria_id=salario.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="500.00",
        data=hoje, descricao="CASHADVANCE", categoria_id=outros.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert "1.000,00" in resposta.text   # rendimento recorrente
    assert "500,00" in resposta.text     # extraordinário, à parte
    assert "Margem estrutural" in resposta.text

    # Controlo decisivo, isolado ao valor da MARGEM ESTRUTURAL especificamente — não ao texto da
    # página inteira. Sem isto, "+1.500,00 €" também apareceria no KPI "Margem Mensal" (que soma
    # total_rendimentos sem distinguir recorrente/extraordinário) neste cenário sem despesas, e a
    # asserção negativa passaria por coincidência mesmo com o bug presente.
    # rindex, não index: a Tarefa 7 consolidou o bloco e "Margem estrutural" passou a aparecer
    # DUAS vezes em home.html — no cabeçalho da secção ("Margem estrutural — rendimento fiável vs.
    # compromissos") e, mais abaixo, no próprio rótulo do valor. rindex apanha esta última
    # ocorrência, que é a que vem imediatamente seguida do valor.
    indice_label = resposta.text.rindex("Margem estrutural")
    fragmento_margem = resposta.text[indice_label:indice_label + 400]
    assert "+1.000,00 €" in fragmento_margem   # só o recorrente
    assert "+1.500,00 €" not in fragmento_margem   # nunca 1000 (recorrente) + 500 (adiantamento)


@pytest.mark.asyncio
async def test_home_rendimentos_marca_natureza_ordinaria_e_extraordinaria(db_session):
    # Achado de 2026-08-20: a secção "Rendimento extraordinário" vivia à parte, numa barra
    # lateral estreita que ficava desalinhada na versão web. Passou a viver dentro de
    # "Rendimentos por fonte" (agora só "Rendimentos"), com uma etiqueta por linha em vez de uma
    # secção separada -- e um filtro para ver só um dos dois lados.
    from datetime import date

    from ava.repositories import categoria_repo
    from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta

    hoje = date.today()
    titular, conta = await criar_titular_e_conta(db_session)
    salario = await criar_categoria(db_session, nome="Salário", tipo="receita", natureza="recorrente")
    grupo_outros = await categoria_repo.criar_grupo(db_session, nome="Outros rendimentos")
    premio = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_outros.id, nome="Prémio", tipo="receita", natureza="extraordinario"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="1000.00",
        data=hoje, categoria_id=salario.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="500.00",
        data=hoje, categoria_id=premio.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert "Rendimento extraordinário" not in resposta.text   # secção antiga, já não existe
    assert 'id="tabela-rendimentos"' in resposta.text
    assert 'id="rendimentos-filtro"' in resposta.text

    indice_salario = resposta.text.index("Salário")
    assert 'data-natureza="ordinaria"' in resposta.text[max(0, indice_salario - 300):indice_salario]
    indice_premio = resposta.text.index("Prémio")
    assert 'data-natureza="extraordinaria"' in resposta.text[max(0, indice_premio - 300):indice_premio]


@pytest.mark.asyncio
async def test_home_rendimentos_sem_categoria_conta_como_extraordinaria(db_session):
    # A mesma regra de segurança que já existia para a margem estrutural (spec §3.3): uma
    # entrada sem categoria não pode ser assumida como fiável, por isso entra como
    # extraordinária -- não desaparece só porque não tem um nome de categoria para mostrar.
    from datetime import date

    from tests.fabricas import criar_movimento, criar_titular_e_conta

    hoje = date.today()
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="300.00",
        data=hoje, categoria_id=None,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    indice_resto = resposta.text.index("300,00")
    fragmento = resposta.text[max(0, indice_resto - 400):indice_resto]
    assert 'data-natureza="extraordinaria"' in fragmento


@pytest.mark.asyncio
async def test_home_mostra_resumo_de_insights(db_session):
    from ava.repositories import categoria_repo, movimento_repo, recorrente_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Subscrições")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Streaming", tipo="despesa", natureza="fixa"
    )
    await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("15.99"), data=date(2026, 8, 6),
        origem="ficheiro", descricao="NETFLIX.COM", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("15.99"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/?periodo=2026-08")

    assert resposta.status_code == 200
    assert "A tua mensalidade de Netflix subiu" in resposta.text
    assert 'href="/insights?periodo=2026-08"' in resposta.text


@pytest.mark.asyncio
async def test_home_sem_insights_nao_mostra_a_seccao(db_session):
    from tests.fabricas import criar_titular_e_conta

    await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert '<h2 class="section-title">Insights</h2>' not in resposta.text


@pytest.mark.asyncio
async def test_dashboard_consolida_margem_num_so_bloco(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert "Este mês" in resposta.text
    assert "Margem estrutural — rendimento fiável vs. compromissos" in resposta.text
    assert "#2563eb" not in resposta.text


@pytest.mark.asyncio
async def test_home_nao_conflacia_saidas_totais_com_margem_bruta(db_session):
    # Regressão: a auto-revisão do plano da Tarefa 7 apanhou este defeito antes de a tarefa ser
    # despachada — o rascunho do bloco "Este mês" chamava "Margem bruta" ao valor que era, na
    # verdade, "Saídas Totais" (despesas + transferências), e nunca chegava a mostrar a margem
    # bruta a sério (rendimentos − saídas). Foi corrigido no texto do plano antes de a tarefa ser
    # implementada, mas ficou sem nenhuma rede de segurança automática contra a reintrodução do
    # mesmo erro (ex. numa futura reedição deste bloco) — é isso que este teste passa a cobrir.
    #
    # `total_transferencias` (ver dashboard.py) só soma transferências SEM categoria — por isso a
    # transferência abaixo fica deliberadamente sem categoria, para total_saidas (despesas +
    # transferências) ser GENUINAMENTE diferente de total_despesas sozinho, e a margem bruta
    # (rendimentos − saídas) diferente de ambos.
    from tests.fabricas import (
        criar_categoria, criar_conta, criar_movimento, criar_titular_e_conta, criar_transferencia,
    )

    hoje = date.today()
    titular, conta = await criar_titular_e_conta(db_session)
    conta_poupanca = await criar_conta(db_session, titular=titular, tipo="poupanca", nome="Poupança")

    salario = await criar_categoria(db_session, nome="Salário", tipo="receita", natureza="recorrente")
    supermercado = await criar_categoria(db_session, nome="Supermercado", tipo="despesa", natureza="variavel")

    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="5000.00",
        data=hoje, categoria_id=salario.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="1200.00",
        data=hoje, categoria_id=supermercado.id,
    )
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=conta_poupanca, valor="800.00", data=hoje,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200

    # Saídas Totais = despesas (1.200) + transferências (800) = 2.000,00 — ancorado ao rótulo, não
    # solto no texto da página inteira. A janela de 200 caracteres fica aquém do bloco "Margem
    # bruta" seguinte (confirmado pela asserção abaixo), por isso não há contaminação cruzada.
    indice_saidas = resposta.text.rindex("Saídas Totais")
    fragmento_saidas = resposta.text[indice_saidas:indice_saidas + 200]
    assert "2.000,00 €" in fragmento_saidas
    assert "Margem bruta" not in fragmento_saidas

    # Margem bruta = rendimentos (5.000) − saídas (2.000) = +3.000,00 — um número DIFERENTE do de
    # cima. Esta é a asserção decisiva: se o bloco voltar a chamar "Margem bruta" ao valor de
    # Saídas Totais (o defeito original desta tarefa), "2.000,00" apareceria aqui em vez de
    # "3.000,00" e este teste falharia.
    indice_margem = resposta.text.rindex("Margem bruta")
    fragmento_margem = resposta.text[indice_margem:indice_margem + 200]
    assert "+3.000,00 €" in fragmento_margem
    assert "2.000,00" not in fragmento_margem


@pytest.mark.asyncio
async def test_home_inclui_alternador_de_tema(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert 'id="theme-toggle"' in resposta.text
    assert "alternarTema" in resposta.text
    assert "ava-tema" in resposta.text


@pytest.mark.asyncio
async def test_barra_inferior_mobile_tem_5_posicoes_e_menu_mais(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert 'class="bottom-tab-bar"' in resposta.text
    assert resposta.text.count("nav-item-cta") == 1
    assert 'id="mais-sheet"' in resposta.text
    # Alertas, Reconciliação, Importar e Configurações vivem só no "Mais" no mobile,
    # mas continuam a aparecer na sidebar — cada um duas vezes no total.
    assert resposta.text.count('href="/reconciliacao"') == 2


@pytest.mark.asyncio
async def test_mais_marca_o_proprio_link_como_ativo(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes", follow_redirects=True)

    assert resposta.status_code == 200
    ocorrencias = re.findall(r'href="/configuracoes"[^>]*class="[^"]*active', resposta.text)
    assert len(ocorrencias) == 2  # sidebar + folha "Mais"


@pytest.mark.asyncio
async def test_movimentos_por_categorizar_usa_cartao_de_registo_nao_tabela(db_session):
    from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=91, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 1), valor=Decimal("-42.00"), descricao="RENOVAR SEGURO",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "RENOVAR SEGURO" in resposta.text
    assert "42,00" in resposta.text
    assert 'class="cartao-registo"' in resposta.text
    assert "<table" not in resposta.text


@pytest.mark.asyncio
async def test_movimentos_por_categorizar_liga_o_seletor_a_deteccao_de_outlier(db_session):
    # Achado da Fase 4: a categoria e o valor têm de chegar a /movimentos/outlier-check quando o
    # utilizador muda a categoria -- sem hx-get/hx-vals no <select>, a dica nunca dispara.
    from ava.repositories import conta_repo, documento_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=92, nivel_extracao=0, dados_extraidos={}
    )
    linha = await linha_extrato_repo.criar_linha(
        db_session, conta_id=conta.id, documento_id=documento.id,
        data=date(2026, 8, 1), valor=Decimal("-42.00"), descricao="RENOVAR SEGURO",
    )
    await linha_extrato_repo.marcar_revisao_manual(db_session, linha.id)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert 'hx-get="/movimentos/outlier-check"' in resposta.text
    assert "hx-vals='{\"valor\": \"42.00\"}'" in resposta.text


@pytest.mark.asyncio
async def test_filtros_de_movimentos_ficam_num_painel_recolhivel(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/movimentos")

    assert resposta.status_code == 200
    assert "<details" in resposta.text
    assert "Filtros" in resposta.text


@pytest.mark.asyncio
async def test_insights_page_agrupa_por_area(db_session):
    from ava.repositories import categoria_repo, movimento_repo, recorrente_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    grupo = await categoria_repo.criar_grupo(db_session, nome="Subscrições")
    categoria = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Streaming", tipo="despesa", natureza="fixa"
    )
    await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("15.99"), data=date(2026, 8, 6),
        origem="ficheiro", descricao="NETFLIX.COM", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("15.99"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/insights?periodo=2026-08")

    assert resposta.status_code == 200
    assert "Despesas" in resposta.text
    assert "A tua mensalidade de Netflix subiu" in resposta.text


@pytest.mark.asyncio
async def test_insights_page_rotula_a_area_saude_com_acento(db_session):
    # Achado ao ligar a Fase 3: sem uma entrada propria em ROTULOS_AREA, "saude" cairia no
    # fallback area.title() = "Saude", sem o acento.
    from ava.repositories import categoria_repo, movimento_repo, ressarcimento_repo
    from tests.fabricas import criar_movimento, criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await categoria_repo.criar_grupo(db_session, nome="Consultas")
    categoria_consultas = await categoria_repo.criar_categoria(
        db_session, grupo_id=consultas.id, nome="Consultas", tipo="despesa", natureza="variavel"
    )
    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="100.00",
        data=date(2026, 8, 15), categoria_id=categoria_consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="20.00",
        data=date(2026, 8, 16), categoria_id=None, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/insights?periodo=2026-08")

    assert resposta.status_code == 200
    assert "Saúde" in resposta.text
    assert "Saude" not in resposta.text
    assert "Recuperaste 20% das tuas despesas de saúde" in resposta.text


@pytest.mark.asyncio
async def test_insights_page_sem_insights_mostra_mensagem(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/insights")

    assert resposta.status_code == 200
    assert "Sem insights para este período." in resposta.text


@pytest.mark.asyncio
async def test_insights_page_mostra_botao_mes_atual_fora_do_mes_atual(db_session):
    # Achado da revisao final de 2026-08-20: /insights reaproveitava a navegacao de periodo do
    # dashboard mas nao o botao "Mes atual" que a acompanha -- depois de recuar varios meses, o
    # unico caminho de volta era o link da barra lateral.
    async with _client_para(db_session) as client:
        resposta_mes_antigo = await client.get("/insights?periodo=2020-01")
        resposta_mes_atual = await client.get("/insights")

    assert resposta_mes_antigo.status_code == 200
    assert 'href="/insights"' in resposta_mes_antigo.text and "Mês atual" in resposta_mes_antigo.text
    assert "Mês atual" not in resposta_mes_atual.text


@pytest.mark.asyncio
async def test_insights_page_recusa_titular_id_invalido_sem_rebentar(db_session):
    # Achado da revisao final: uuid.UUID(titular_id) sem guarda levantava ValueError -> 500 nao
    # tratado para um valor de query nao parsavel.
    async with _client_para(db_session) as client:
        resposta = await client.get("/insights?titular_id=nao-e-um-uuid")

    assert resposta.status_code == 200


@pytest.mark.asyncio
async def test_insights_page_mostra_seletor_de_fornecedores_com_despesas(db_session):
    from ava.repositories import fornecedor_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    sem_despesa = await fornecedor_repo.obter_ou_criar(db_session, nome="Sem Despesa", tipo="outro")
    await db_session.commit()
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("83.39"), data=date(2026, 8, 7),
        origem="documento", fornecedor_id=fornecedor.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("83.39"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/insights")

    assert resposta.status_code == 200
    assert f'value="{fornecedor.id}"' in resposta.text
    assert "EDP" in resposta.text
    assert f'value="{sem_despesa.id}"' not in resposta.text


@pytest.mark.asyncio
async def test_insights_page_mostra_historico_ao_escolher_fornecedor(db_session):
    from ava.repositories import fornecedor_repo, movimento_repo
    from tests.fabricas import criar_titular_e_conta

    titular, conta = await criar_titular_e_conta(db_session)
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("83.39"), data=date(2026, 8, 7),
        origem="documento", fornecedor_id=fornecedor.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("83.39"))],
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/insights?fornecedor_id={fornecedor.id}")

    assert resposta.status_code == 200
    assert "83,39" in resposta.text
    assert "07/08/2026" in resposta.text


@pytest.mark.asyncio
async def test_insights_page_sem_fornecedor_selecionado_nao_mostra_tabela(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/insights")

    assert resposta.status_code == 200
    assert "Sem pagamentos registados para este fornecedor." not in resposta.text


@pytest.mark.asyncio
async def test_insights_page_recusa_fornecedor_id_invalido_sem_rebentar(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/insights?fornecedor_id=nao-e-um-uuid")

    assert resposta.status_code == 200


@pytest.mark.asyncio
async def test_insights_page_usa_a_navegacao_partilhada_da_app(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/insights")

    assert resposta.status_code == 200
    assert 'class="sidebar"' in resposta.text
    assert 'class="bottom-tab-bar"' in resposta.text


@pytest.mark.asyncio
async def test_nav_sidebar_tem_link_para_insights(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/")

    assert resposta.status_code == 200
    assert 'href="/insights"' in resposta.text
