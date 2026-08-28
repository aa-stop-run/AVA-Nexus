import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from ava.db import get_session
from ava.main import create_app
from ava.repositories import ativo_repo, ativo_valor_repo, categoria_repo, titular_repo


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_configuracoes_categorias_lista_grupos_e_categorias(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Renda", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/categorias")

    assert resposta.status_code == 200
    assert "Habitação" in resposta.text
    assert "Renda" in resposta.text


@pytest.mark.asyncio
async def test_post_grupo_cria_e_aparece_na_listagem(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/grupos", data={"nome": "Animais"}, follow_redirects=True
        )

    assert resposta.status_code == 200
    assert "Animais" in resposta.text


@pytest.mark.asyncio
async def test_post_grupo_com_nome_repetido_mostra_erro_sem_duplicar(db_session):
    await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post("/configuracoes/grupos", data={"nome": "Habitação"})

    assert resposta.status_code == 422
    assert "já existe" in resposta.text.lower()

    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)
    assert len(todos) == 1


@pytest.mark.asyncio
async def test_post_categoria_cria_dentro_do_grupo_escolhido(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Animais", ordem=1)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Veterinário",
                "tipo": "despesa",
                "natureza": "variavel",
            },
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    assert "Veterinário" in resposta.text

    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)
    categorias = dict(todos)[grupo]
    assert [c.nome for c in categorias] == ["Veterinário"]


@pytest.mark.asyncio
async def test_post_categoria_despesa_grava_a_natureza_escolhida(db_session):
    # Task 4: a rota deixou de ter um default de natureza (ver criar_categoria_route) — agora a
    # UI escolhe-a explicitamente e a rota grava exatamente o que veio no formulário. Sem este
    # teste, um bug que ignorasse o valor submetido e voltasse a gravar sempre "variavel" (ou
    # qualquer outro valor fixo) passaria despercebido.
    grupo = await categoria_repo.criar_grupo(db_session, nome="Animais", ordem=1)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Veterinário",
                "tipo": "despesa",
                "natureza": "variavel",
            },
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    categoria = await categoria_repo.obter_por_nomes(db_session, grupo="Animais", nome="Veterinário")
    assert categoria is not None
    assert categoria.natureza == "variavel"


@pytest.mark.asyncio
async def test_post_categoria_receita_grava_a_natureza_escolhida(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Outros rendimentos", ordem=1)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Cashback",
                "tipo": "receita",
                "natureza": "extraordinario",
            },
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    categoria = await categoria_repo.obter_por_nomes(db_session, grupo="Outros rendimentos", nome="Cashback")
    assert categoria is not None
    assert categoria.natureza == "extraordinario"


@pytest.mark.asyncio
async def test_post_categoria_com_nome_repetido_no_mesmo_grupo_mostra_erro(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Renda", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Renda",
                "tipo": "despesa",
                "natureza": "variavel",
            },
        )

    assert resposta.status_code == 422
    assert "já tem uma categoria" in resposta.text.lower()

    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)
    categorias = dict(todos)[grupo]
    assert len(categorias) == 1


@pytest.mark.asyncio
async def test_post_categoria_com_grupo_inexistente_mostra_erro(db_session):
    import uuid

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(uuid.uuid4()),
                "nome": "Qualquer",
                "tipo": "despesa",
                "natureza": "variavel",
            },
        )

    assert resposta.status_code == 422
    assert "seleção inválida" in resposta.text.lower()


@pytest.mark.asyncio
async def test_post_categoria_com_tipo_invalido_mostra_erro(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Renda",
                "tipo": "invalido",
                "natureza": "variavel",
            },
        )

    assert resposta.status_code == 422
    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)
    assert dict(todos)[grupo] == []


@pytest.mark.asyncio
async def test_post_grupo_com_nome_demasiado_longo_mostra_erro(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.post("/configuracoes/grupos", data={"nome": "x" * 61})

    assert resposta.status_code == 422
    assert "máximo" in resposta.text.lower()

    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)
    assert todos == []


@pytest.mark.asyncio
async def test_post_grupo_corrida_toctou_devolve_erro_amigavel_em_vez_de_500(db_session, monkeypatch):
    # Simula a corrida descrita na revisão: a pré-verificação (snapshot já obtido) não vê o nome
    # como duplicado, mas o INSERT real colide com a constraint única da BD (ex.: outro pedido
    # quase simultâneo criou o mesmo nome entretanto). O handler deve devolver 422 com a mesma
    # mensagem amigável, nunca deixar o IntegrityError propagar como 500.
    import ava.api.configuracoes as configuracoes_module

    async def _criar_grupo_que_colide(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))

    monkeypatch.setattr(configuracoes_module.categoria_repo, "criar_grupo", _criar_grupo_que_colide)

    async with _client_para(db_session) as client:
        resposta = await client.post("/configuracoes/grupos", data={"nome": "Animais"})

    assert resposta.status_code == 422
    assert "já existe" in resposta.text.lower()

    # A sessão continua utilizável depois do rollback (não fica presa numa transação abortada).
    async with _client_para(db_session) as client:
        resposta_seguinte = await client.get("/configuracoes/categorias")
    assert resposta_seguinte.status_code == 200


@pytest.mark.asyncio
async def test_post_categoria_corrida_toctou_devolve_erro_amigavel_em_vez_de_500(db_session, monkeypatch):
    import ava.api.configuracoes as configuracoes_module

    grupo = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    await db_session.commit()

    async def _criar_categoria_que_colide(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))

    monkeypatch.setattr(configuracoes_module.categoria_repo, "criar_categoria", _criar_categoria_que_colide)

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Renda",
                "tipo": "despesa",
                "natureza": "variavel",
            },
        )

    assert resposta.status_code == 422
    assert "já tem uma categoria" in resposta.text.lower()

    async with _client_para(db_session) as client:
        resposta_seguinte = await client.get("/configuracoes/categorias")
    assert resposta_seguinte.status_code == 200


# --- Património (Bens / Ativos) ---
#
# Rota e página descobertas na Task 9 sem um único teste — era o segundo caminho de criação de
# ativos (além de /ativos/novo), esquecido pelo plano original de valorização de ativos. Estes
# testes cobrem o que a migração para ativo_valor precisa de continuar a garantir.


@pytest.mark.asyncio
async def test_get_patrimonio_mostra_valor_formatado_quando_ha_avaliacao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo="carro")
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date.today(), valor=Decimal("8500.00"), origem="aquisicao"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    assert "Corsa" in resposta.text
    assert "8.500,00" in resposta.text


@pytest.mark.asyncio
async def test_get_patrimonio_mostra_sem_avaliacao_quando_nao_ha_valor(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Mota", tipo="mota")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    assert "Mota" in resposta.text
    assert "Sem avaliação" in resposta.text


@pytest.mark.asyncio
async def test_get_patrimonio_marca_valor_projetado_como_estimado(db_session):
    # Ronda de correção 1/5: /configuracoes/patrimonio calculava e_projetado mas nunca o
    # mostrava, deixando uma estimativa passar por valor observado. Ver patrimonio.html:112-116
    # para o padrão original que este teste espelha.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo="carro")
    # Observação antiga -> o valor de hoje é projetado.
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2020, 1, 1), valor=Decimal("20000.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    assert "estimado" in resposta.text


@pytest.mark.asyncio
async def test_get_patrimonio_mostra_data_de_avaliacao_quando_nao_e_projetado(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo="carro")
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date.today(), valor=Decimal("8500.00"), origem="aquisicao"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    assert "avaliado em" in resposta.text
    assert date.today().strftime("%d/%m/%Y") in resposta.text
    assert "estimado" not in resposta.text


@pytest.mark.asyncio
async def test_post_ativo_com_valor_valido_cria_ativo_e_avaliacao_de_aquisicao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/ativos",
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

    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id)
    assert len(historico) == 1
    assert historico[0].valor == Decimal("8500.00")
    assert historico[0].data == date(2022, 3, 10)
    assert historico[0].origem == "aquisicao"


@pytest.mark.asyncio
async def test_post_ativo_sem_valor_cria_ativo_sem_avaliacao(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/ativos",
            data={"titular_id": str(titular.id), "nome": "Mota", "tipo": "mota"},
        )

    assert resposta.status_code in (200, 303)

    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert len(ativos) == 1
    assert await ativo_valor_repo.listar_por_ativo(db_session, ativos[0].id) == []


@pytest.mark.asyncio
async def test_post_ativo_com_valor_invalido_nao_cria_ativo_e_mostra_erro(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/ativos",
            data={"titular_id": str(titular.id), "nome": "Barco", "tipo": "outro", "valor_atual": "abc"},
        )

    assert resposta.status_code == 200
    assert "valor inválido" in resposta.text.lower()
    assert await ativo_repo.listar_todos_ativos(db_session) == []


@pytest.mark.asyncio
async def test_post_ativo_com_data_aquisicao_futura_nao_cria_nada(db_session):
    # A data de aquisição alimenta diretamente a avaliação "aquisicao" (registar_valor). Uma
    # data futura meteria uma observação no futuro em ativo_valor, corrompendo o KPI de
    # património e a série do gráfico da home, tal como uma avaliação futura em
    # /patrimonio/ativos/{id}/avaliacao.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    data_futura = (date.today() + timedelta(days=1)).isoformat()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/ativos",
            data={
                "titular_id": str(titular.id),
                "nome": "Corsa",
                "tipo": "carro",
                "valor_atual": "8500.00",
                "data_aquisicao": data_futura,
            },
        )

    assert resposta.status_code == 200
    assert "futuro" in resposta.text.lower()
    assert await ativo_repo.listar_todos_ativos(db_session) == []


@pytest.mark.asyncio
async def test_post_ativo_casa_valoriza_com_a_taxa_de_casa_no_criado_em_configuracoes(db_session):
    # Regressão: /configuracoes/ativos oferecia tipo="imovel", que não existe em
    # valorizacao.TAXAS_POR_TIPO — uma casa criada aqui ficava presa a taxa 0 em silêncio, em vez
    # dos +2%/ano que a spec define. O formulário agora só oferece o vocabulário canónico
    # (carro | mota | casa | outro); este teste confirma que "casa" projeta com a taxa certa.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    data_aquisicao = (date.today() - timedelta(days=400)).isoformat()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/ativos",
            data={
                "titular_id": str(titular.id),
                "nome": "Casa Lisboa",
                "tipo": "casa",
                "valor_atual": "200000.00",
                "data_aquisicao": data_aquisicao,
            },
        )

    assert resposta.status_code in (200, 303)

    ativos = await ativo_repo.listar_todos_ativos(db_session)
    assert len(ativos) == 1
    ativo = ativos[0]
    assert ativo.tipo == "casa"

    avaliacao = await ativo_repo.valor_atual(db_session, ativo)
    assert avaliacao is not None
    # A taxa de "casa" é positiva (+2%/ano): mais de um ano depois, o valor projetado tem de ser
    # MAIOR do que o observado — se "casa" caísse (em silêncio) na taxa 0 de um tipo desconhecido
    # (o bug que "imovel" causava), o valor ficaria estagnado nos 200000.00 originais.
    assert avaliacao.valor > Decimal("200000.00")
    assert avaliacao.e_projetado is True


# --- Ligar a dívida ao bem (Task 2) ---


@pytest.mark.asyncio
async def test_post_liga_divida_ao_bem(db_session):
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", categoria_divida="habitacao",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/ativo", data={"ativo_id": str(casa.id)}
        )

    assert resposta.status_code in (200, 303)
    await db_session.refresh(conta)
    assert conta.ativo_id == casa.id


@pytest.mark.asyncio
async def test_post_com_ativo_vazio_desliga(db_session):
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", ativo_id=casa.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(f"/configuracoes/contas/{conta.id}/ativo", data={"ativo_id": ""})

    await db_session.refresh(conta)
    assert conta.ativo_id is None


@pytest.mark.asyncio
async def test_post_recusa_ativo_inexistente(db_session):
    import uuid as _uuid

    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/ativo", data={"ativo_id": str(_uuid.uuid4())}
        )

    assert resposta.status_code == 404
    await db_session.refresh(conta)
    assert conta.ativo_id is None


@pytest.mark.asyncio
async def test_post_recusa_ativo_id_malformado(db_session):
    # Um ativo_id que nem sequer é um UUID válido deve dar o mesmo 404 que um ativo
    # inexistente, não um 500 por ValueError não apanhado no uuid.UUID(...).
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/ativo", data={"ativo_id": "nao-e-um-uuid"}
        )

    assert resposta.status_code == 404
    await db_session.refresh(conta)
    assert conta.ativo_id is None


@pytest.mark.asyncio
async def test_post_recusa_conta_que_nao_e_divida(db_session):
    # Uma conta à ordem não financiou bem nenhum.
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    casa = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Casa", tipo="casa"
    )
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/ativo", data={"ativo_id": str(casa.id)}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_configuracoes_patrimonio_mostra_seletor_de_bem_nas_dividas(db_session):
    from ava.repositories import ativo_repo, conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Casa", tipo="casa")
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida",
        nome="Mortgage & Loans", categoria_divida="habitacao",
    )
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    # Um seletor só — o da dívida. A conta à ordem não o tem.
    assert resposta.text.count('name="ativo_id"') == 1
    assert "Casa" in resposta.text


# --- Âncora manual (Task 7) ---
#
# /configuracoes/contas/{conta_id}/saldo é a segunda e última fonte de âncoras, a par do
# extrato (spec §7.3). Existe para contas sem extrato (cartões de refeição) e para corrigir
# uma âncora errada.


@pytest.mark.asyncio
async def test_post_saldo_manual_cria_a_ancora(db_session):
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    cartao = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Edenred",
        tipo="cartao_refeicao", nome="Cartão Refeição",
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{cartao.id}/saldo",
            data={"data": "2026-08-08", "valor": "556.80"},
        )

    assert resposta.status_code == 303
    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, cartao.id)
    assert ancora.valor == Decimal("556.80")
    assert ancora.origem == "manual"


@pytest.mark.asyncio
async def test_post_saldo_manual_substitui_a_ancora_do_mesmo_dia(db_session):
    # Corrigir um engano nao pode falhar com "ja existe saldo nessa data".
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 8), valor=Decimal("100.00")
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        await client.post(
            f"/configuracoes/contas/{conta.id}/saldo",
            data={"data": "2026-08-08", "valor": "250.00"},
        )

    ancoras = await saldo_historico_repo.listar_evolucao(db_session, conta.id)
    assert len(ancoras) == 1
    assert ancoras[0].valor == Decimal("250.00")
    assert ancoras[0].origem == "manual"


@pytest.mark.asyncio
async def test_post_saldo_manual_recusa_data_futura(db_session):
    from datetime import timedelta

    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    amanha = (date.today() + timedelta(days=1)).isoformat()
    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/saldo", data={"data": amanha, "valor": "10.00"}
        )

    assert resposta.status_code == 400
    assert await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id) is None


@pytest.mark.asyncio
async def test_post_saldo_manual_aceita_separador_de_milhares(db_session):
    # REGRESSAO (revisao final, achado 2): o campo mostra o placeholder "0,00" e format_pt
    # escreve os valores da app assim -- "4.281,55" -- mas o parse fazia só
    # valor.replace(",", "."), que trocava a virgula e deixava os pontos de milhares intocados:
    # "4.281,55" virava "4.281.55", InvalidOperation. Este e o PRIMEIRO uso previsto da app: o
    # utilizador a declarar o saldo real da conta a ordem, um valor de quatro digitos.
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/saldo",
            data={"data": "2026-08-08", "valor": "4.281,55"},
        )

    assert resposta.status_code == 303
    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert ancora.valor == Decimal("4281.55")


@pytest.mark.asyncio
async def test_post_saldo_manual_recusa_valor_nao_numerico(db_session):
    # O 400 nos casos genuinamente invalidos mantem-se -- só o "," com pontos de milhares deixa
    # de rebentar.
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{conta.id}/saldo",
            data={"data": "2026-08-08", "valor": "abc"},
        )

    assert resposta.status_code == 400
    assert await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id) is None


@pytest.mark.asyncio
async def test_post_saldo_manual_recusa_conta_inexistente(db_session):
    import uuid as _uuid

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/contas/{_uuid.uuid4()}/saldo",
            data={"data": "2026-08-08", "valor": "10.00"},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_configuracoes_patrimonio_mostra_o_formulario_de_saldo(db_session):
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/patrimonio")

    assert resposta.status_code == 200
    assert 'name="valor"' in resposta.text
    assert "/saldo" in resposta.text


# --- Redesenho visual (Task 6) ---


@pytest.mark.asyncio
async def test_separador_configuracoes_patrimonio_chama_se_patrimonio(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/titulares")

    assert resposta.status_code == 200
    assert re.search(r">\s*Património\s*</a>", resposta.text)
    assert "Contratos & Bens" not in resposta.text
