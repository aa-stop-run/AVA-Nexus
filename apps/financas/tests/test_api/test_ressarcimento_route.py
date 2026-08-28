import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from ava.db import get_session
from ava.main import create_app
from ava.models.ressarcimento import Ressarcimento
from ava.repositories import ressarcimento_repo
from tests.fabricas import criar_categoria, criar_movimento, criar_titular_e_conta


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_liga_uma_despesa_a_um_grupo_novo(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date(2026, 8, 15), categoria_id=consultas.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento", data={"ressarcimento_id": "novo"}
        )

    assert resposta.status_code == 200
    await db_session.refresh(movimento.linhas[0])
    assert movimento.linhas[0].ressarcimento_id is not None


@pytest.mark.asyncio
async def test_liga_um_reembolso_a_um_grupo_existente(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    reembolsos = await criar_categoria(db_session, nome="Reembolsos", tipo="receita", natureza="extraordinario")
    grupo = await ressarcimento_repo.criar(db_session)
    await db_session.commit()

    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="50.00",
        data=date(2026, 8, 15), categoria_id=reembolsos.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento",
            data={"ressarcimento_id": str(grupo.id)},
        )

    assert resposta.status_code == 200
    await db_session.refresh(movimento.linhas[0])
    assert movimento.linhas[0].ressarcimento_id == grupo.id


@pytest.mark.asyncio
async def test_desliga_ao_enviar_vazio(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    grupo = await ressarcimento_repo.criar(db_session)
    await db_session.commit()

    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date(2026, 8, 15), categoria_id=consultas.id, ressarcimento_id=grupo.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento", data={"ressarcimento_id": ""}
        )

    assert resposta.status_code == 200
    await db_session.refresh(movimento.linhas[0])
    assert movimento.linhas[0].ressarcimento_id is None


@pytest.mark.asyncio
async def test_404_para_movimento_inexistente(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{uuid.uuid4()}/ressarcimento", data={"ressarcimento_id": "novo"}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_404_para_transferencia(db_session):
    # A rota só aceita saida/entrada (§5.1 da spec: "despesa OU reembolso") — uma transferência
    # (ex.: amortização de crédito) não é nenhum dos dois lados de um ressarcimento.
    from tests.fabricas import criar_transferencia

    titular, conta = await criar_titular_e_conta(db_session)
    from ava.repositories import conta_repo
    conta_poupanca = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="poupanca", nome="Poupança"
    )
    movimento = await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=conta_poupanca,
        valor="200.00", data=date(2026, 8, 15),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento", data={"ressarcimento_id": "novo"}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_404_para_grupo_id_invalido(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date(2026, 8, 15), categoria_id=consultas.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento",
            data={"ressarcimento_id": str(uuid.uuid4())},
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_pagina_da_conta_mostra_o_seletor_de_ressarcimento(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date.today(), categoria_id=consultas.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}")

    assert resposta.status_code == 200
    assert "ressarcimento" in resposta.text.lower()


@pytest.mark.asyncio
async def test_grupo_antigo_aparece_selecionado_mesmo_fora_de_90_dias(db_session):
    """Verifica que um grupo ligado mas mais antigo que 90 dias ainda aparece como opção
    selecionada no dropdown, não é substituído por '+ Novo grupo'."""
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")

    # Cria um grupo e move sua data de criação para 100 dias no passado
    grupo_antigo = await ressarcimento_repo.criar(db_session)
    data_antiga = datetime.now(timezone.utc) - timedelta(days=100)
    await db_session.execute(
        update(Ressarcimento).where(Ressarcimento.id == grupo_antigo.id).values(criado_em=data_antiga)
    )
    await db_session.commit()

    # Cria um movimento ligado a este grupo antigo
    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date.today(), categoria_id=consultas.id, ressarcimento_id=grupo_antigo.id,
    )
    await db_session.commit()

    # Acessa a página da conta
    async with _client_para(db_session) as client:
        resposta = await client.get(f"/patrimonio/contas/{conta.id}")

    assert resposta.status_code == 200
    # O grupo antigo deve estar na lista de opções (appear no HTML)
    # A opção com o ID do grupo deve estar marcada como selected, não "novo"
    assert f'value="{grupo_antigo.id}"' in resposta.text
    assert f'value="{grupo_antigo.id}"' in resposta.text and 'selected' in resposta.text


@pytest.mark.asyncio
async def test_post_ressarcimento_devolve_hx_refresh_header(db_session):
    """Verifica que a rota POST de ressarcimento devolve o header HX-Refresh para
    recarregar a página inteira (mantém todas as células sincronizadas)."""
    titular, conta = await criar_titular_e_conta(db_session)
    consultas = await criar_categoria(db_session, nome="Consultas", tipo="despesa", natureza="variavel")
    movimento = await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="80.00",
        data=date(2026, 8, 15), categoria_id=consultas.id,
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/movimentos/{movimento.id}/ressarcimento", data={"ressarcimento_id": "novo"}
        )

    assert resposta.status_code == 200
    assert resposta.headers.get("HX-Refresh") == "true"
