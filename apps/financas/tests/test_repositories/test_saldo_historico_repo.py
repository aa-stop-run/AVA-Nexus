from datetime import date, timedelta
from decimal import Decimal

import pytest

from ava.repositories import conta_repo, saldo_historico_repo, titular_repo
from ava.repositories.saldo_historico_repo import SaldoDuplicado
from tests.fabricas import criar_conta, criar_movimento, criar_titular_e_conta, criar_transferencia


@pytest.mark.asyncio
async def test_registar_saldo_assume_origem_extrato(db_session):
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    saldo = await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("100.00")
    )
    assert saldo.origem == "extrato"


@pytest.mark.asyncio
async def test_registar_saldo_aceita_origem_manual(db_session):
    _, conta = await criar_titular_e_conta(db_session, tipo="cartao_refeicao")
    saldo = await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8),
        valor=Decimal("250.00"), origem="manual",
    )
    assert saldo.origem == "manual"


@pytest.mark.asyncio
async def test_registar_saldo_e_listar_evolucao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )

    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("1200.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 7, 31), valor=Decimal("1350.00")
    )
    await db_session.commit()

    evolucao = await saldo_historico_repo.listar_evolucao(db_session, conta.id)
    assert [s.valor for s in evolucao] == [Decimal("1200.00"), Decimal("1350.00")]

    mais_recente = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert mais_recente.valor == Decimal("1350.00")


@pytest.mark.asyncio
async def test_registar_saldo_duplicado_na_mesma_data_e_rejeitado(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("1200.00")
    )
    await db_session.commit()

    with pytest.raises(SaldoDuplicado):
        await saldo_historico_repo.registar_saldo(
            db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("1250.00")
        )


@pytest.mark.asyncio
async def test_saldo_duplicado_nao_reverte_outro_trabalho_pendente_na_sessao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="CGD", tipo="a_ordem", nome="Conta à ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("1200.00")
    )
    await db_session.commit()

    # Outro trabalho pendente na mesma sessão, ainda não commitado.
    outro_titular = await titular_repo.criar_titular(db_session, nome="Maria Silva", tipo="individual")

    with pytest.raises(SaldoDuplicado):
        await saldo_historico_repo.registar_saldo(
            db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("1250.00")
        )

    # O rollback do INSERT duplicado deve ficar confinado ao SAVEPOINT: o
    # titular criado antes (ainda não commitado) tem de sobreviver na sessão.
    titular_ainda_presente = await titular_repo.obter_titular(db_session, outro_titular.id)
    assert titular_ainda_presente is not None
    assert titular_ainda_presente.nome == "Maria Silva"


@pytest.mark.asyncio
async def test_listar_patrimonio_liquido_no_tempo_agrega_ativos_e_dividas(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Teste", tipo="adulto")
    await db_session.flush()

    conta_ordem = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta Ordem"
    )
    conta_divida = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Cartão"
    )
    await db_session.flush()

    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ordem.id, data=date(2026, 6, 1), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_divida.id, data=date(2026, 6, 1), valor=Decimal("200.00")
    )
    # 15/07: só a conta à ordem tem saldo novo -- a dívida deve continuar a contar com o
    # último valor conhecido (200.00), não desaparecer nem zerar.
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ordem.id, data=date(2026, 7, 15), valor=Decimal("1500.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    # Sem bens nesta série, financeiro e total coincidem em cada data. O último ponto é "hoje"
    # (Task 10) — sem movimentos depois das âncoras, repete o valor da última âncora de cada
    # conta. `e_estimado` é False: nenhuma conta tem movimento nenhum depois da sua âncora, por
    # isso o ponto de hoje é tão facto confirmado quanto os históricos (achado 3 da re-revisão —
    # antes desta correção, este último ponto vinha sempre True, mesmo sem estimativa nenhuma).
    assert serie == [
        (date(2026, 6, 1), Decimal("800.00"), Decimal("800.00"), False),   # 1000 - 200
        (date(2026, 7, 15), Decimal("1300.00"), Decimal("1300.00"), False),  # 1500 - 200 (dívida mantém o último valor)
        (date.today(), Decimal("1300.00"), Decimal("1300.00"), False),
    ]


@pytest.mark.asyncio
async def test_serie_nao_projeta_o_valor_de_hoje_para_o_passado(db_session):
    # Regressão: a versão anterior somava ativo.valor_atual a TODAS as datas desde a aquisição,
    # fazendo o passado parecer que o carro sempre valeu o que vale agora.
    from ava.repositories import ativo_repo, ativo_valor_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2025, 1, 1), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 1, 1), valor=Decimal("1000.00")
    )
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    # Só há observação a partir de 2026 — em 2025 o valor do carro é desconhecido.
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)
    por_data = {d: (fin, tot) for d, fin, tot, _ in serie}

    # 2025: o carro ainda não tinha avaliação -> não entra no total.
    assert por_data[date(2025, 1, 1)] == (Decimal("1000.00"), Decimal("1000.00"))
    # 2026: entra pelo valor observado.
    assert por_data[date(2026, 1, 1)] == (Decimal("1000.00"), Decimal("9000.00"))


@pytest.mark.asyncio
async def test_serie_devolve_financeiro_e_total(db_session):
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Conta"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 1, 1), valor=Decimal("500.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    # Task 10: o ponto de hoje ("estimado") acresce ao ponto histórico.
    assert len(serie) == 2
    data_ref, financeiro, total, e_estimado = serie[0]
    assert data_ref == date(2026, 1, 1)
    assert financeiro == Decimal("500.00")
    assert total == Decimal("500.00")  # sem bens, os dois números coincidem
    assert e_estimado is False


@pytest.mark.asyncio
async def test_saldo_derivado_soma_os_movimentos_depois_da_ancora(db_session):
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="150.00", data=date(2026, 8, 5), conta=conta, titular=titular
    )
    await db_session.commit()

    derivado = await saldo_historico_repo.saldo_derivado(db_session, conta, ate=date(2026, 8, 10))
    assert derivado.valor == Decimal("850.00")
    assert derivado.ancora_valor == Decimal("1000.00")
    assert derivado.ancora_data == date(2026, 8, 3)
    assert derivado.e_estimado is True


@pytest.mark.asyncio
async def test_saldo_derivado_ignora_movimentos_anteriores_a_ancora(db_session):
    # A âncora já os contém.
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await criar_movimento(
        db_session, tipo="saida", valor="500.00", data=date(2026, 7, 20), conta=conta, titular=titular
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await db_session.commit()

    derivado = await saldo_historico_repo.saldo_derivado(db_session, conta, ate=date(2026, 8, 10))
    assert derivado.valor == Decimal("1000.00")
    assert derivado.e_estimado is False


@pytest.mark.asyncio
async def test_saldo_derivado_de_um_emprestimo_desce_com_a_amortizacao(db_session):
    titular, ordem = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Ordem")
    credito = await criar_conta(db_session, titular=titular, tipo="emprestimo", nome="Credito")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=credito.id, data=date(2026, 7, 3), valor=Decimal("152433.26")
    )
    await criar_transferencia(
        db_session, valor="463.19", data=date(2026, 8, 3), origem=ordem, destino=credito, titular=titular
    )
    await db_session.commit()

    derivado = await saldo_historico_repo.saldo_derivado(db_session, credito, ate=date(2026, 8, 10))
    assert derivado.valor == Decimal("151970.07")


@pytest.mark.asyncio
async def test_saldo_derivado_sem_ancora_devolve_none(db_session):
    # Uma soma de movimentos sem ponto de partida não é um saldo. O UI mostra "—", não 0,00.
    titular, conta = await criar_titular_e_conta(db_session, tipo="cartao_credito")
    await criar_movimento(
        db_session, tipo="saida", valor="40.00", data=date(2026, 8, 5), conta=conta, titular=titular
    )
    await db_session.commit()

    assert await saldo_historico_repo.saldo_derivado(db_session, conta) is None


@pytest.mark.asyncio
async def test_saldo_derivado_usa_a_ancora_mais_recente(db_session):
    # É assim que uma âncora manual corrige um histórico partido (spec §11).
    _, conta = await criar_titular_e_conta(db_session, tipo="cartao_refeicao")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 6, 30), valor=Decimal("192.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8),
        valor=Decimal("556.80"), origem="manual",
    )
    await db_session.commit()

    derivado = await saldo_historico_repo.saldo_derivado(db_session, conta, ate=date(2026, 8, 10))
    assert derivado.valor == Decimal("556.80")
    assert derivado.ancora_origem == "manual"


@pytest.mark.asyncio
async def test_evolucao_acrescenta_o_ponto_de_hoje_estimado(db_session):
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="150.00", data=date.today(), conta=conta, titular=titular
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    assert serie[-1][0] == date.today()
    assert serie[-1][1] == Decimal("850.00")
    assert serie[-1][3] is True   # e_estimado
    assert all(ponto[3] is False for ponto in serie[:-1])


@pytest.mark.asyncio
async def test_evolucao_nao_duplica_hoje_se_ja_houver_ancora_de_hoje(db_session):
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date.today(), valor=Decimal("1000.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)
    assert len([p for p in serie if p[0] == date.today()]) == 1


@pytest.mark.asyncio
async def test_evolucao_ancora_de_hoje_numa_conta_nao_esconde_movimentos_de_outra(db_session):
    # REGRESSAO (revisao final, achado 4): "if resultado and hoje not in {...}" saltava o ponto
    # DERIVADO de hoje inteiro assim que QUALQUER conta tivesse uma ancora de hoje -- mesmo que
    # outras contas tivessem movimentos por derivar desde uma ancora mais antiga. O ponto
    # historico de hoje usava o "last known value" (a ancora crua), sem os movimentos da outra
    # conta.
    titular, conta_ancora_hoje = await criar_titular_e_conta(db_session, tipo="a_ordem", nome="Conta A")
    conta_com_movimentos = await criar_conta(db_session, titular=titular, tipo="poupanca", nome="Conta B")

    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_ancora_hoje.id, data=date.today(), valor=Decimal("500.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta_com_movimentos.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="150.00", data=date.today(),
        conta=conta_com_movimentos, titular=titular,
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    assert serie[-1][0] == date.today()
    # 500.00 (ancora de hoje, sem movimentos) + 850.00 (1000 - 150, DERIVADO) = 1350.00
    assert serie[-1][1] == Decimal("1350.00")
    assert serie[-1][3] is True  # e_estimado


@pytest.mark.asyncio
async def test_evolucao_avaliacao_de_bem_hoje_nao_esconde_movimentos_de_conta(db_session):
    # Mesmo achado 4, pelo ramo dos bens: uma avaliacao datada de hoje tambem mete "hoje" no
    # conjunto de datas historicas (datas.add(avaliacao.data)) -- o mesmo efeito colateral de uma
    # ancora de hoje, só que ninguem tinha testado este ramo até a revisão final.
    from ava.repositories import ativo_repo, ativo_valor_repo

    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="150.00", data=date.today(), conta=conta, titular=titular
    )
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Carro", tipo="carro")
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date.today(), valor=Decimal("5000.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    assert serie[-1][0] == date.today()
    assert serie[-1][1] == Decimal("850.00")    # financeiro: 1000 - 150, DERIVADO
    assert serie[-1][2] == Decimal("5850.00")   # total: financeiro + bem
    assert serie[-1][3] is True                 # e_estimado


@pytest.mark.asyncio
async def test_evolucao_ancora_de_hoje_sem_movimentos_nao_e_estimado(db_session):
    # REGRESSAO (re-revisao, achado 3): o e_estimado do ponto de hoje ficava fixo em True depois
    # de a correcao anterior o passar a acrescentar sempre. Com uma ancora de hoje e nenhum
    # movimento desde ela, o valor e identico ao confirmado -- nao e estimativa nenhuma, e o
    # grafico nao devia desenha-lo tracejado.
    _, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date.today(), valor=Decimal("1000.00")
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    assert serie[-1][0] == date.today()
    assert serie[-1][1] == Decimal("1000.00")
    assert serie[-1][3] is False  # e_estimado


@pytest.mark.asyncio
async def test_evolucao_ancora_com_movimento_depois_e_estimado(db_session):
    # Contraste com o teste acima: a ancora aqui NAO pode estar datada de hoje -- fluxo_entre
    # exclui o proprio dia da ancora (`Movimento.data > de`, ver a docstring de
    # movimento_repo.fluxo_entre), por isso um movimento "depois" de uma ancora de hoje nunca
    # existiria dentro do intervalo (hoje, hoje]. Com a ancora uns dias atras e um movimento
    # registado depois dela, o valor deixa de ser o que a ancora declarou -- volta a ser
    # estimativa.
    titular, conta = await criar_titular_e_conta(db_session, tipo="a_ordem")
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date.today() - timedelta(days=3), valor=Decimal("1000.00")
    )
    await criar_movimento(
        db_session, tipo="saida", valor="50.00", data=date.today(), conta=conta, titular=titular
    )
    await db_session.commit()

    serie = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(db_session)

    assert serie[-1][0] == date.today()
    assert serie[-1][1] == Decimal("950.00")
    assert serie[-1][3] is True  # e_estimado
