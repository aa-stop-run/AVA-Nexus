from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app
from tests.fabricas import criar_movimento, criar_movimento_manual, criar_titular_e_conta


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_reconciliacao_mostra_janela_que_nao_fecha(db_session):
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 10), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("800.00")
    )
    # O banco diz -200; o razao so explica -150. Faltam 50.
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="150.00", data=date(2026, 8, 20)
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "50,00" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_ignora_janelas_anteriores_ao_corte(db_session):
    # RECONCILIACAO_DESDE = 2026-08-08 (spec §11).
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 5, 1), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 6, 1), valor=Decimal("700.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert "300,00" not in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_mostra_movimento_por_confirmar_antigo(db_session):
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 8, 20), descricao="Nunca apareceu",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert "Nunca apareceu" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_tabela_de_por_confirmar_tem_scroll_horizontal_proprio(db_session):
    # Achado de 2026-08-21 (revisão de mobile): as 3 tabelas desta página eram <table> nuas, sem
    # wrapper -- em ecrãs estreitos, a linha com o formulário "Dispensar" (input de texto + botão)
    # empurrava a página inteira para o lado, 311px de scroll horizontal medidos em produção a
    # 390px de largura. Sem dados de divergência para testar essa tabela especificamente, esta
    # cobre a de "por confirmar", que partilha a mesma correção (div.overflow-x-auto).
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 8, 20), descricao="Nunca apareceu",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert '<div class="overflow-x-auto">\n  <table class="table-clean">' in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_ignora_conta_cuja_ultima_ancora_e_manual(db_session):
    # A lista afirma "o banco teve oportunidade de mostrar isto e nao mostrou". Essa afirmacao so
    # se pode fazer se o banco tiver falado DEPOIS do movimento -- e a ultima ancora e a ultima
    # palavra dele. Se essa palavra e do utilizador, o banco nao falou desde entao e a acusacao
    # nao tem fundamento.
    #
    # O caso real que isto resolve: os cartoes de refeicao nao tem extrato nem exportacao, so
    # ancoras manuais. Sem esta regra, cada almoco registado apareceria aqui para sempre a partir
    # da segunda ancora manual -- a "lista que grita sempre" que a spec 6.3 proibe, garantida.
    from ava.repositories import saldo_historico_repo

    titular, cartao = await criar_titular_e_conta(
        db_session, tipo="cartao_refeicao", nome="Cartão Refeição"
    )
    await criar_movimento_manual(
        db_session, titular=titular, conta=cartao,
        valor="7.50", data=date(2026, 8, 20), descricao="Almoco de agosto",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=cartao.id, data=date(2026, 9, 10),
        valor=Decimal("250.00"), origem="manual",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "Almoco de agosto" not in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_ignora_conta_cuja_ultima_ancora_e_de_ficheiro(db_session):
    # Contraste com test_reconciliacao_mostra_movimento_por_confirmar_antigo: so a origem da
    # ancora muda. Um ficheiro do BPI Net nao prova cobertura de periodo nenhuma -- o proprio
    # rodape dele avisa que so traz o que estava no ecra, sem garantir nenhum inicio. Uma ancora
    # de ficheiro recente nao pode acusar um movimento manual antigo de nunca ter sido mostrado
    # pelo banco (ronda de correcao 1, Important #4): a mesma pausa que ja se aplica a ancora
    # manual aplica-se aqui, e pelo mesmo motivo -- a ultima palavra nao prova que o banco falou.
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 8, 20), descricao="Nunca apareceu",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10),
        valor=Decimal("1000.00"), origem="ficheiro",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "Nunca apareceu" not in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_mostra_a_mesma_conta_quando_a_ancora_e_de_extrato(db_session):
    # O contraste do teste anterior: tudo igual menos a origem da ancora. So a diferenca entre os
    # dois prova que a regra discrimina pela PROVENIENCIA da ultima palavra, e nao por acaso.
    from ava.repositories import saldo_historico_repo

    titular, cartao = await criar_titular_e_conta(
        db_session, tipo="cartao_refeicao", nome="Cartão Refeição"
    )
    await criar_movimento_manual(
        db_session, titular=titular, conta=cartao,
        valor="7.50", data=date(2026, 8, 20), descricao="Almoco de agosto",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=cartao.id, data=date(2026, 9, 10),
        valor=Decimal("250.00"), origem="extrato",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "Almoco de agosto" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_usa_a_ancora_de_extrato_mesmo_com_ficheiro_mais_recente(db_session):
    # Achado 6 da revisao final: a versao antiga usava "a ancora mais recente, seja ela qual
    # for" como referencia do limite, e so saltava a conta quando essa origem era
    # manual/ficheiro. O raciocinio estava certo mas o efeito nao: como se importa o ficheiro
    # varias vezes por mes e o extrato chega uma vez, a ancora mais recente da conta principal
    # era quase sempre "ficheiro" -- e a lista ficava apagada ~28 dias em 30. Aqui a ancora de
    # ficheiro (20/09) e MAIS RECENTE do que a de extrato (10/09), e o movimento tem de aparecer
    # na mesma: a referencia certa e a ultima vez que o EXTRATO provou cobertura.
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 8, 20), descricao="Nunca apareceu",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10),
        valor=Decimal("1000.00"), origem="extrato",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 20),
        valor=Decimal("1050.00"), origem="ficheiro",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    # 20/08 e anterior a 10/09 - 7 = 03/09 -- tem de aparecer.
    assert "Nunca apareceu" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_nao_grita_com_movimento_dos_ultimos_sete_dias(db_session):
    # REGRESSAO do falso alarme mensal (spec §6.3): uma compra a 5/9 lanca a 8/9 e aparece so no
    # extrato de outubro. Com a ancora a 10/9, esta dentro da margem e nao e suspeita.
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 9, 5), descricao="Ainda vai a tempo",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert "Ainda vai a tempo" not in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_mostra_o_manual_e_esconde_o_de_regra(db_session):
    # Um movimento origem="regra" (gerado por gerar_movimentos_recorrentes_do_mes) ja tem alerta
    # proprio em ingestion/reconciliacao.py ("nunca foi debitado/creditado") e e deliberadamente
    # excluido do casamento (ingestion/casamento.py: "tem outro dono e outro ciclo de vida") -
    # por isso tenderia a ficar sem linha_extrato_id para sempre e apareceria aqui todos os meses.
    #
    # Controlo positivo NA MESMA condicao (mesma conta, mesma data, mesmo valor, por confirmar,
    # mais antigo que a margem): um movimento origem="manual" identico em tudo menos a origem e a
    # descricao. So a diferenca entre os dois asserts prova que o filtro DISCRIMINA por origem —
    # um so assert negativo passaria tambem com a pagina partida, a seccao a nao renderizar, ou
    # listar_por_confirmar_antigos sempre vazio, sem o filtro do "regra" estar la (mesmo defeito
    # do "-" da Task 9 e dos dois True da Task 8).
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="33.00",
        data=date(2026, 8, 20), descricao="Mensalidade recorrente", origem="regra",
    )
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="33.00", data=date(2026, 8, 20), descricao="Despesa registada a mao",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("1000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "Despesa registada a mao" in resposta.text       # o manual aparece
    assert "Mensalidade recorrente" not in resposta.text    # o regra nao


@pytest.mark.asyncio
async def test_reconciliacao_nao_mostra_movimento_de_ficheiro_por_confirmar(db_session):
    # Um movimento vindo de um ficheiro do banco nao e "registaste isto e o banco nunca o
    # mostrou" -- veio dele. Continua por confirmar ate o EXTRATO o mostrar (spec §5), mas nao
    # tem que estar na lista de suspeitos.
    from ava.repositories import movimento_repo, saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("33.00"), data=date(2026, 8, 20),
        origem="ficheiro", descricao="COMPRA ELEC do ficheiro",
        conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("33.00"), categoria_id=None)],
    )
    await criar_movimento_manual(
        db_session, titular=titular, conta=conta,
        valor="44.00", data=date(2026, 8, 20), descricao="Registado a mao",
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10),
        valor=Decimal("1000.00"), origem="extrato",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    # O contraste prova que a exclusao e por ORIGEM e nao por a pagina estar partida.
    assert "Registado a mao" in resposta.text
    assert "COMPRA ELEC do ficheiro" not in resposta.text


@pytest.mark.asyncio
async def test_dispensar_remove_da_lista_e_persiste(db_session):
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 10), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("800.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            "/reconciliacao/dispensar",
            data={"conta_id": str(conta.id), "data": "2026-09-10",
                  "valor": "-200.00", "motivo": "extrato de agosto perdido"},
        )
        resposta = await client.get("/reconciliacao")

    assert "200,00" not in resposta.text


@pytest.mark.asyncio
async def test_dispensar_duas_vezes_a_mesma_janela_e_inocuo(db_session):
    # Duplo clique, ou voltar atras e reenviar o formulario: a unicidade e (conta_id, data), e
    # sem tratamento o segundo POST rebentava com IntegrityError nao apanhado -> 500.
    from ava.models.divergencia_aceite import DivergenciaAceite
    from ava.repositories import saldo_historico_repo
    from sqlalchemy import select

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 10), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("800.00")
    )
    await db_session.commit()

    dados = {
        "conta_id": str(conta.id), "data": "2026-09-10",
        "valor": "-200.00", "motivo": "extrato de agosto perdido",
    }

    async with _client_para(db_session) as client:
        primeira = await client.post("/reconciliacao/dispensar", data=dados, follow_redirects=False)
        segunda = await client.post("/reconciliacao/dispensar", data=dados, follow_redirects=False)

    assert primeira.status_code == 303
    assert segunda.status_code == 303

    resultado = await db_session.execute(
        select(DivergenciaAceite).where(DivergenciaAceite.conta_id == conta.id)
    )
    assert len(resultado.scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_lista_cura_se_sozinha(db_session):
    # A divergencia e CALCULADA, nao escrita: classificar o movimento em falta fa-la
    # desaparecer sem ninguem a apagar (spec §10).
    from ava.repositories import saldo_historico_repo

    titular, conta = await criar_titular_e_conta(db_session)
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 10), valor=Decimal("1000.00")
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 9, 10), valor=Decimal("800.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        antes = await client.get("/reconciliacao")
        assert "200,00" in antes.text

    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="200.00", data=date(2026, 8, 20)
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        depois = await client.get("/reconciliacao")
    assert "200,00" not in depois.text


@pytest.mark.asyncio
async def test_reconciliacao_mostra_extratos_importados_recentemente(db_session):
    from ava.repositories import documento_repo

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=921, nivel_extracao=0, dados_extraidos={}
    )
    documento.resumo_ingestao = {
        "contas": [{"conta": "Ordem BPI", "criadas": 12, "saltadas": 135}]
    }
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert "Ordem BPI" in resposta.text
    assert "135" in resposta.text
    assert "12" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_ignora_documentos_sem_resumo(db_session):
    # Duas asserções, ambas positivas. A exclusão é verificada no repositório (uma lista exata),
    # não por "922 not in resposta.text": um número de três dígitos aparece por acaso numa
    # página cheia de valores, e um teste que depende disso passa ou falha por sorte.
    from datetime import timedelta

    from ava.repositories import documento_repo

    await documento_repo.criar_documento(
        db_session, paperless_document_id=922, nivel_extracao=0, dados_extraidos={}
    )
    com_resumo = await documento_repo.criar_documento(
        db_session, paperless_document_id=923, nivel_extracao=0, dados_extraidos={}
    )
    com_resumo.resumo_ingestao = {
        "contas": [{"conta": "Conta Visivel", "criadas": 3, "saltadas": 0}]
    }
    await db_session.commit()

    listados = await documento_repo.listar_com_resumo_de_ingestao(
        db_session, desde=date.today() - timedelta(days=1)
    )
    assert [d.paperless_document_id for d in listados] == [923]

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert "Conta Visivel" in resposta.text


@pytest.mark.asyncio
async def test_reconciliacao_mostra_conta_reprocessada_uma_so_vez(db_session):
    # Achado Importante da revisao final: sem o upsert por conta em _persistir_extrato, um
    # documento reprocessado (corrida automatica + aprovacao manual, fluxo normal) acrescentava
    # uma entrada REPETIDA por conta a resumo_ingestao["contas"] em vez de a substituir -- a
    # mesma conta aparecia duas vezes na tabela, com numeros diferentes.
    #
    # Este teste simula diretamente o RESULTADO do upsert (uma lista com uma unica entrada para
    # "Ordem BPI", os valores da passagem mais recente) e confirma que a pagina renderizada
    # mostra essa conta exatamente uma vez -- ao nivel de _persistir_extrato, o upsert em si ja
    # tem cobertura em test_pipeline.py; aqui o que importa e que o template nao introduza uma
    # segunda ocorrencia por conta sua (ex.: um segundo loop, ou nao respeitar a lista tal como
    # veio da base).
    from ava.repositories import documento_repo

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=924, nivel_extracao=0, dados_extraidos={}
    )
    documento.resumo_ingestao = {
        "contas": [{"conta": "Ordem BPI", "criadas": 0, "saltadas": 147}]
    }
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/reconciliacao")

    assert resposta.status_code == 200
    assert resposta.text.count("Ordem BPI") == 1
