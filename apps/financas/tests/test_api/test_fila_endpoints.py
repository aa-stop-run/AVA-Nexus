import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from ava.api.deps import get_paperless_client
from ava.db import get_session
from ava.main import create_app
from ava.repositories import documento_repo, fila_repo, movimento_repo, titular_repo


class FakePaperless:
    def __init__(self):
        self.tags_removidas: list[int] = []

    async def obter_id_de_tag(self, nome: str) -> int:
        return 42

    async def remover_tag(self, document_id: int, tag_id: int) -> None:
        self.tags_removidas.append(document_id)


@pytest.mark.asyncio
async def test_worker_pede_proximo_e_submete_resultado_valido(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=1, dados_extraidos={}
    )
    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto ocr aqui")
    await db_session.commit()

    app = create_app()

    async def override_get_session():
        yield db_session

    fake_paperless = FakePaperless()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_paperless_client] = lambda: fake_paperless
    headers = {"Authorization": "Bearer test-worker-token"}
    data_limite_data = date.today() + timedelta(days=3)
    data_limite = data_limite_data.isoformat()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resposta = await client.get("/api/fila/proximo", headers=headers)
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["item_id"] == str(item.id)

        resposta = await client.post(
            f"/api/fila/{item.id}/resultado",
            headers=headers,
            json={
                "resultado": {
                    "fornecedor_nome": "MEO",
                    "nif_emissor": None,
                    "iban": None,
                    "valor_total": "29.99",
                    "data_limite_pagamento": data_limite,
                    "linhas": [],
                    "consumo": None,
                }
            },
        )
        assert resposta.status_code == 204

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"
    assert fake_paperless.tags_removidas == [1]

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=data_limite_data, fim=data_limite_data
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("29.99")


@pytest.mark.asyncio
async def test_worker_submete_resultado_de_extrato_bancario(db_session):
    # exercises the extrato_bancario branch added to submeter_resultado's dispatch (Task 22),
    # through the real HTTP endpoint — the same path that proves the despesa_avulsa ordering
    # fix (see test_retry_despesa_avulsa_nao_duplica_transacao above).
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=8, nivel_extracao=1, dados_extraidos={}, registado_por=titular.id
    )
    item = await fila_repo.criar_item(
        db_session, documento_id=documento.id, texto_ocr="texto ocr", tipo="extrato_bancario"
    )
    await db_session.commit()

    app = create_app()

    async def override_get_session():
        yield db_session

    fake_paperless = FakePaperless()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_paperless_client] = lambda: fake_paperless
    headers = {"Authorization": "Bearer test-worker-token"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resposta = await client.post(
            f"/api/fila/{item.id}/resultado",
            headers=headers,
            json={
                "resultado": {
                    "instituicao": "CGD",
                    "tipo_conta": "a_ordem",
                    "nome_conta": "Conta à Ordem",
                    "saldo_final": {"data": date.today().isoformat(), "valor": "1350.00"},
                    # checksum (Task 8): sem movimentos, saldo_inicial tem de igualar saldo_final.
                    "saldo_inicial": "1350.00",
                    "movimentos": [],
                }
            },
        )
        assert resposta.status_code == 204

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"
    assert fake_paperless.tags_removidas == [8]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    assert contas[0].instituicao == "CGD"


@pytest.mark.asyncio
async def test_endpoint_recusa_token_invalido(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resposta = await client.get("/api/fila/proximo", headers={"Authorization": "Bearer errado"})

    assert resposta.status_code == 401


@pytest.mark.asyncio
async def test_worker_pede_proximo_e_submete_erro(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=2, nivel_extracao=1, dados_extraidos={}
    )
    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto ocr aqui")
    await db_session.commit()

    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers = {"Authorization": "Bearer test-worker-token"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resposta = await client.get("/api/fila/proximo", headers=headers)
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["item_id"] == str(item.id)
        assert corpo["texto_ocr"] == "texto ocr aqui"

        resposta = await client.post(
            f"/api/fila/{item.id}/erro",
            headers=headers,
            json={"mensagem": "timeout do modelo"},
        )
        assert resposta.status_code == 204

    atualizado = await fila_repo.obter_por_id(db_session, item.id)
    assert atualizado.estado == "erro"
    assert atualizado.resultado_json == {"erro": "timeout do modelo"}


@pytest.mark.asyncio
async def test_endpoint_erro_retorna_404_para_item_inexistente(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers = {"Authorization": "Bearer test-worker-token"}

    item_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resposta = await client.post(
            f"/api/fila/{item_id}/erro",
            headers=headers,
            json={"mensagem": "error"},
        )
        assert resposta.status_code == 404
