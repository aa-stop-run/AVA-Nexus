from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import categoria_repo, insights_repo, movimento_repo, recorrente_repo, ressarcimento_repo
from tests.fabricas import criar_conta, criar_movimento, criar_titular_e_conta, criar_transferencia


async def _categoria_despesa(db_session, nome="Streaming"):
    grupo = await categoria_repo.criar_grupo(db_session, nome=f"Grupo {nome}")
    return await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=nome, tipo="despesa", natureza="fixa"
    )


async def _categoria_rendimento(db_session, nome="Salário"):
    grupo = await categoria_repo.criar_grupo(db_session, nome=f"Grupo {nome}")
    return await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome=nome, tipo="receita", natureza="recorrente"
    )


@pytest.mark.asyncio
async def test_listar_insights_deteta_mensalidade_que_subiu(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    recorrente = await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("15.99"), data=date(2026, 8, 6),
        origem="ficheiro", descricao="NETFLIX.COM", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("15.99"))],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    mensalidade = [i for i in insights if i.tipo == f"mensalidade:{recorrente.id}"]
    assert len(mensalidade) == 1
    assert mensalidade[0].tom == "atencao"


@pytest.mark.asyncio
async def test_listar_insights_ignora_recorrente_sem_movimento_real(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    assert insights == []


@pytest.mark.asyncio
async def test_listar_insights_ignora_movimento_de_origem_regra(db_session):
    # Um movimento "regra" com um valor bem diferente do recorrente prova que a exclusão de
    # origem funciona -- se a query o contasse como candidato, isto dispararia o insight
    # (diferença bem acima do limiar de 1%).
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    recorrente = await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("99.99"), data=date(2026, 8, 5),
        origem="regra", descricao="Netflix", conta_id=conta.id, titular_id=titular.id,
        recorrente_id=recorrente.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("99.99"))],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    mensalidade = [i for i in insights if i.tipo == f"mensalidade:{recorrente.id}"]
    assert mensalidade == []


@pytest.mark.asyncio
async def test_listar_insights_recorrente_sem_conta_e_ignorado(db_session):
    titular, _conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=None, valor=Decimal("12.99"), dia_do_mes=5, descricao="Sem conta",
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    assert insights == []


@pytest.mark.asyncio
async def test_listar_insights_inclui_tendencia_da_margem(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_rendimento(db_session)
    # Rendimento recorrente grande só em agosto -- margem alta em agosto, ~0 nos 3 meses
    # anteriores (sem movimento nenhum), diferença bem acima do limiar de 50€.
    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("2000.00"), data=date(2026, 8, 10),
        origem="manual", descricao="Salário", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("2000.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    tendencias = [i for i in insights if i.tipo == "tendencia_margem"]
    assert len(tendencias) == 1
    assert tendencias[0].tom == "positivo"
    assert len(tendencias[0].serie) == 6


@pytest.mark.asyncio
async def test_margens_dos_ultimos_6_meses_usa_margem_atual_quando_fornecida(db_session):
    # Achado da revisao final de 2026-08-20: dashboard.py::home() ja calcula a margem do mes
    # atual antes de chamar listar_insights -- sem este parametro, a mesma consulta pesada
    # (margem_estrutural, uma juncao a 4 tabelas) corria uma segunda vez para o mesmo periodo.
    # Um valor claramente distinto do que seria calculado de raiz (sem movimentos, seria 0)
    # prova que o override e mesmo usado, nao ignorado.
    titular, _conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    margens = await insights_repo._margens_dos_ultimos_6_meses(
        db_session, ano=2026, mes=8, titular_id=titular.id, margem_atual=Decimal("999.99"),
    )

    assert len(margens) == 6
    assert margens[-1] == Decimal("999.99")


@pytest.mark.asyncio
async def test_listar_insights_rejeita_candidato_fora_da_banda_de_plausibilidade(db_session):
    # Achado da revisao final de 2026-08-20: sem banda de plausibilidade, uma compra grande e
    # nao relacionada perto da data do recorrente era lida como "a mensalidade subiu".
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    recorrente = await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    # Fora da banda (12.99 * 1.5 = 19.485): uma compra de supermercado nao relacionada, perto da data.
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("87.40"), data=date(2026, 8, 6),
        origem="ficheiro", descricao="SUPERMERCADO", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("87.40"))],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    mensalidade = [i for i in insights if i.tipo == f"mensalidade:{recorrente.id}"]
    assert mensalidade == []


@pytest.mark.asyncio
async def test_listar_insights_nao_deixa_dois_recorrentes_reclamarem_o_mesmo_movimento(db_session):
    # Achado da revisao final: dois recorrentes faturados no mesmo dia nao podem ambos "encontrar"
    # o mesmo movimento real -- so o primeiro (por ordem de dia_do_mes, depois id) fica com ele.
    #
    # Achado da re-revisao (fix wave): a primeira versao deste teste usava Spotify=9.99 e um
    # movimento de 14.99 -- fora da propria banda de plausibilidade do Spotify (max 14.985), por
    # isso o teste passava mesmo sem excluir_ids fazer nada (o filtro de banda ja rejeitava o
    # Spotify sozinho). Os valores abaixo colocam o movimento DENTRO da banda dos dois
    # recorrentes (Netflix 12.99 -> [6.495, 19.485]; Outro 13.50 -> [6.75, 20.25]; movimento
    # 13.20 esta nas duas), para o teste so passar se o dedup estiver mesmo a funcionar.
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session)
    netflix = await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("12.99"), dia_do_mes=5, descricao="Netflix",
    )
    outro = await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("13.50"), dia_do_mes=5, descricao="Outro",
    )
    # Um unico movimento real, dentro da banda de plausibilidade de AMBOS os recorrentes.
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("13.20"), data=date(2026, 8, 5),
        origem="ficheiro", descricao="COBRANCA", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("13.20"))],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    mensalidade_netflix = [i for i in insights if i.tipo == f"mensalidade:{netflix.id}"]
    mensalidade_outro = [i for i in insights if i.tipo == f"mensalidade:{outro.id}"]
    # So um dos dois pode ter encontrado o movimento (netflix.dia_do_mes == outro.dia_do_mes,
    # por isso o desempate e por id de recorrente -- listar_ativos ordena por dia_do_mes, id).
    # Sem o dedup, os DOIS o encontrariam (esta dentro da banda de ambos) e total seria 2.
    total_com_insight = len(mensalidade_netflix) + len(mensalidade_outro)
    assert total_com_insight == 1


@pytest.mark.asyncio
async def test_listar_insights_ordena_atencao_primeiro(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    categoria_despesa = await _categoria_despesa(db_session)
    categoria_rendimento = await _categoria_rendimento(db_session)
    # Mensalidade que SUBIU (tom atenção) -- 40% de subida: acima do limiar de 1% mas dentro da
    # banda de plausibilidade (50%-150%), para não colidir com a proteção contra falsos positivos.
    await recorrente_repo.criar_recorrente(
        db_session, tipo="saida", categoria_id=categoria_despesa.id, titular_id=titular.id,
        conta_id=conta.id, valor=Decimal("10.00"), dia_do_mes=5, descricao="Spotify",
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("14.00"), data=date(2026, 8, 6),
        origem="ficheiro", descricao="SPOTIFY", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("14.00"))],
    )
    # Margem em alta (tom positivo)
    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("2000.00"), data=date(2026, 8, 10),
        origem="manual", descricao="Salário", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("2000.00"), categoria_id=categoria_rendimento.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    assert len(insights) >= 2
    assert insights[0].tom == "atencao"
    assert any(i.tom == "positivo" for i in insights[1:])


@pytest.mark.asyncio
async def test_listar_insights_inclui_tendencia_de_categoria(db_session):
    # Achado de 2026-08-20 (Fase 2): despesas constantes nos 3 meses anteriores + uma subida
    # clara no mes em avaliacao deve gerar um insight de tendencia por categoria.
    titular, conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session, nome="Alimentação")
    for mes, dia in ((5, 10), (6, 10), (7, 10)):
        await movimento_repo.criar_movimento(
            db_session, tipo="saida", valor=Decimal("500.00"), data=date(2026, mes, dia),
            origem="manual", descricao="Compras", conta_id=conta.id, titular_id=titular.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal("500.00"), categoria_id=categoria.id)],
        )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("650.00"), data=date(2026, 8, 10),
        origem="manual", descricao="Compras", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("650.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    tendencias = [i for i in insights if i.tipo.startswith("tendencia_categoria:")]
    assert len(tendencias) == 1
    assert tendencias[0].tipo == "tendencia_categoria:Grupo Alimentação"
    assert tendencias[0].tom == "atencao"
    assert len(tendencias[0].serie) == 6


@pytest.mark.asyncio
async def test_totais_por_grupo_ultimos_6_meses_usa_despesas_atuais_quando_fornecidas(db_session):
    # Mesma razao do teste equivalente para margem_atual: prova que o override e mesmo usado,
    # nao ignorado, com um total que nunca sairia de uma consulta real (a conta nao tem
    # movimentos nenhuns).
    from ava.models.categoria import Categoria
    from ava.models.grupo_categoria import GrupoCategoria

    titular, _conta = await criar_titular_e_conta(db_session)
    categoria = await _categoria_despesa(db_session, nome="Teste")
    await db_session.commit()
    await db_session.refresh(categoria)
    grupo = await db_session.get(GrupoCategoria, categoria.grupo_id)

    despesas_atuais = [(grupo, categoria, Decimal("777.00"))]

    resultado = await insights_repo._totais_por_grupo_ultimos_6_meses(
        db_session, ano=2026, mes=8, titular_id=titular.id, despesas_atuais=despesas_atuais,
    )

    nomes_e_series = dict(resultado)
    assert nomes_e_series[grupo.nome][-1] == Decimal("777.00")


@pytest.mark.asyncio
async def test_listar_insights_inclui_taxa_de_recuperacao_de_ressarcimento(db_session):
    from datetime import date

    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await _categoria_despesa(db_session, nome="Consultas")
    grupo = await ressarcimento_repo.criar(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="100.00",
        data=date(2026, 8, 15), categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="20.00",
        data=date(2026, 8, 16), categoria_id=None, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    recuperacao = [i for i in insights if i.tipo == "recuperacao_ressarcimento"]
    assert len(recuperacao) == 1
    assert recuperacao[0].tom == "atencao"
    assert recuperacao[0].titulo == "Recuperaste 20% das tuas despesas de saúde"


@pytest.mark.asyncio
async def test_poupancas_dos_ultimos_6_meses_usa_poupanca_atual_quando_fornecida(db_session):
    # Mesmo padrao de test_margens_dos_ultimos_6_meses_usa_margem_atual_quando_fornecida: o
    # dashboard.py::home() ja calcula a margem (logo tambem a poupanca) do mes atual antes de
    # chamar listar_insights -- sem este override a consulta de margem_estrutural correria uma
    # segunda vez para o mesmo periodo.
    titular, _conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    poupancas = await insights_repo._poupancas_dos_ultimos_6_meses(
        db_session, ano=2026, mes=8, titular_id=titular.id, poupanca_atual=Decimal("999.99"),
    )

    assert len(poupancas) == 6
    assert poupancas[-1] == Decimal("999.99")


@pytest.mark.asyncio
async def test_listar_insights_inclui_projecao_de_poupanca(db_session):
    # Transferencia de uma conta a_ordem para uma poupanca: classe_de_conta(origem)=corrente,
    # classe_de_conta(destino)=poupanca -- classificar_fluxo devolve "poupanca" e o sinal e
    # positivo (so e negativo quando a classe de ORIGEM e que e poupanca, ver natureza.py). 3
    # meses seguidos de 200,00 € guardados cumprem o minimo de 3 meses e o limiar de 50 €/mes de
    # calcular_projecao_poupanca.
    titular, ordem = await criar_titular_e_conta(db_session)
    poupanca = await criar_conta(db_session, titular=titular, tipo="poupanca", nome="Poupança")
    for data in (date(2026, 6, 10), date(2026, 7, 10), date(2026, 8, 10)):
        await criar_transferencia(
            db_session, titular=titular, origem=ordem, destino=poupanca, valor="200.00", data=data,
        )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    projecoes = [i for i in insights if i.tipo == "projecao_poupanca"]
    assert len(projecoes) == 1
    assert projecoes[0].tom == "positivo"
    assert "1.200,00" in projecoes[0].titulo


@pytest.mark.asyncio
async def test_listar_insights_inclui_runway_emergencia(db_session):
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 1), valor=Decimal("10000.00")
    )
    categoria = await _categoria_despesa(db_session, nome="Alimentação")
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("1000.00"), data=date(2026, 8, 5),
        origem="manual", descricao="Supermercado", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("1000.00"), categoria_id=categoria.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    runway = [i for i in insights if i.tipo == "runway_emergencia"]
    assert len(runway) == 1
    assert runway[0].area == "patrimonio"


@pytest.mark.asyncio
async def test_listar_insights_inclui_sazonalidade_utilities(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    eletricidade = await _categoria_despesa(db_session, nome="Eletricidade")
    # Ano anterior (agosto de 2025): 80€
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("80.00"), data=date(2025, 8, 10),
        origem="manual", descricao="EDP", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("80.00"), categoria_id=eletricidade.id)],
    )
    # Mês atual (agosto de 2026): 130€ (+50€ / +62.5% > 20% e > 25€)
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("130.00"), data=date(2026, 8, 10),
        origem="manual", descricao="EDP", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("130.00"), categoria_id=eletricidade.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    utilities = [i for i in insights if i.tipo == "sazonalidade_utility:Eletricidade"]
    assert len(utilities) == 1
    assert utilities[0].tom == "atencao"
    assert "face ao ano anterior" in utilities[0].titulo


@pytest.mark.asyncio
async def test_listar_insights_inclui_racio_custos_fixos(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    rendimento = await _categoria_rendimento(db_session, nome="Salário")
    despesa = await _categoria_despesa(db_session, nome="Renda")  # natureza: fixa
    # Salário: 2.000€
    await movimento_repo.criar_movimento(
        db_session, tipo="entrada", valor=Decimal("2000.00"), data=date(2026, 8, 1),
        origem="manual", descricao="Salário", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("2000.00"), categoria_id=rendimento.id)],
    )
    # Renda: 1.200€ (60% > 50%)
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("1200.00"), data=date(2026, 8, 5),
        origem="manual", descricao="Renda", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("1200.00"), categoria_id=despesa.id)],
    )
    await db_session.commit()

    insights = await insights_repo.listar_insights(db_session, ano=2026, mes=8, titular_id=titular.id)

    racio = [i for i in insights if i.tipo == "racio_custos_fixos"]
    assert len(racio) == 1
    assert racio[0].tom == "atencao"
    assert "60%" in racio[0].valor

