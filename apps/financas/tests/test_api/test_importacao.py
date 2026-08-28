import pathlib
from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from ava.api.deps import get_paperless_client
from ava.db import get_session
from ava.main import create_app
from ava.models.movimento import Movimento
from tests.fabricas import criar_titular_e_conta

_EXEMPLO = pathlib.Path(__file__).parent.parent / "ficheiros" / "extmovs_bpi_exemplo.xlsx"


def _client_para(db_session):
    app = create_app()

    async def override():
        yield db_session

    app.dependency_overrides[get_session] = override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class FakePaperlessEnvio:
    """Grava as chamadas a enviar_documento, sem tocar num Paperless real."""

    def __init__(self):
        self.chamadas: list[dict] = []

    async def enviar_documento(self, *, conteudo: bytes, nome_ficheiro: str, tags: list[str] | None = None) -> None:
        self.chamadas.append({"conteudo": conteudo, "nome_ficheiro": nome_ficheiro, "tags": tags})


@pytest.mark.asyncio
async def test_importa_o_ficheiro_real(db_session):
    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("extmovs.xlsx", _EXEMPLO.read_bytes(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert resposta.status_code == 303
    movimentos = (await db_session.execute(
        select(Movimento).where(Movimento.conta_id == conta.id)
    )).scalars().all()
    assert len(movimentos) == 180
    assert all(m.origem == "ficheiro" for m in movimentos)


@pytest.mark.asyncio
async def test_recusa_um_ficheiro_que_nao_e_xlsx(db_session):
    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("dados.csv", b"a,b,c", "text/csv")},
        )

    assert resposta.status_code == 303
    assert "erro" in str(resposta.headers["location"])
    movimentos = (await db_session.execute(
        select(Movimento).where(Movimento.conta_id == conta.id)
    )).scalars().all()
    assert movimentos == []


@pytest.mark.asyncio
async def test_um_ficheiro_ilegivel_nao_grava_nada(db_session):
    # Recusa-se INTEIRO: importar metade seria pior do que nao importar nada.
    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("x.xlsx", b"nao e um xlsx", "application/octet-stream")},
        )

    assert resposta.status_code == 303
    assert "erro" in str(resposta.headers["location"])
    movimentos = (await db_session.execute(
        select(Movimento).where(Movimento.conta_id == conta.id)
    )).scalars().all()
    assert movimentos == []


@pytest.mark.asyncio
async def test_importacao_que_levanta_devolve_redirect_com_erro_em_vez_de_500(db_session, monkeypatch):
    # Achado 5 da revisao final: o parser ja filtra as linhas de valor zero conhecidas, mas a
    # rota nao tinha nenhum tratamento para o que ainda escapasse dele -- uma excecao do
    # repositorio (ValorNaoPositivo/SomaDasLinhasNaoBate) rebentava com um 500 mudo. Simula o
    # caso "desconhecido" substituindo `importar` por uma versao que levanta, para provar que a
    # ROTA (nao so o parser) tem a segunda linha de defesa.
    from ava.api import importacao as importacao_route
    from ava.repositories.movimento_repo import ValorNaoPositivo

    async def _importar_que_rebenta(*args, **kwargs):
        raise ValorNaoPositivo("movimento.valor tem de ser positivo, recebido 0")

    monkeypatch.setattr(importacao_route, "importar", _importar_que_rebenta)

    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("extmovs.xlsx", _EXEMPLO.read_bytes(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert resposta.status_code == 303
    assert "erro" in str(resposta.headers["location"])
    movimentos = (await db_session.execute(
        select(Movimento).where(Movimento.conta_id == conta.id)
    )).scalars().all()
    assert movimentos == []


@pytest.mark.asyncio
async def test_mensagem_reporta_cobertos_pelo_extrato_separadamente_de_ja_existiam(db_session, monkeypatch):
    # Minor da revisao da revisao final: as linhas saltadas por sobreposicao com o extrato nunca
    # chegaram a existir como movimento -- "ja existiam" seria falso sobre elas. A mensagem tem
    # de reportar os dois contadores com frases diferentes e verdadeiras.
    from urllib.parse import unquote

    from ava.api import importacao as importacao_route
    from ava.ingestion.importacao_ficheiro import ResultadoImportacao

    async def _importar_fake(*args, **kwargs):
        return ResultadoImportacao(criados=1, casados=0, saltados=2, cobertos_pelo_extrato=176, ancora=None)

    monkeypatch.setattr(importacao_route, "importar", _importar_fake)

    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("extmovs.xlsx", _EXEMPLO.read_bytes(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    mensagem = unquote(str(resposta.headers["location"]))
    assert "2 já existiam" in mensagem
    assert "176 já cobertos pelo extrato" in mensagem


@pytest.mark.asyncio
async def test_mensagem_omite_cobertos_pelo_extrato_quando_zero(db_session):
    # Contraste: sem nenhuma linha coberta pelo extrato (o caso comum, sem ancora de extrato
    # nenhuma), a frase nao aparece -- para nao engordar a mensagem em toda importacao normal.
    from urllib.parse import unquote

    _, conta = await criar_titular_e_conta(db_session)
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/importar",
            data={"conta_id": str(conta.id)},
            files={"file": ("extmovs.xlsx", _EXEMPLO.read_bytes(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    mensagem = unquote(str(resposta.headers["location"]))
    assert "cobertos pelo extrato" not in mensagem


@pytest.mark.asyncio
async def test_a_pagina_de_importacao_abre(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/importar")
    assert resposta.status_code == 200


# --- Upload de extrato PDF para o Paperless ---


def _client_com_paperless(db_session, fake_paperless):
    app = create_app()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_paperless_client] = lambda: fake_paperless
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_upload_de_extrato_envia_ao_paperless_com_as_tags_certas(db_session):
    from ava.repositories import titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.commit()

    fake_paperless = FakePaperlessEnvio()
    async with _client_com_paperless(db_session, fake_paperless) as client:
        resposta = await client.post(
            "/importar/extrato",
            data={"titular_id": str(titular.id)},
            files={"file": ("extrato.pdf", b"%PDF-conteudo-fake", "application/pdf")},
        )

    assert resposta.status_code == 303
    assert len(fake_paperless.chamadas) == 1
    chamada = fake_paperless.chamadas[0]
    assert chamada["nome_ficheiro"] == "extrato.pdf"
    assert chamada["conteudo"] == b"%PDF-conteudo-fake"
    assert chamada["tags"] == ["extrato-por-estruturar", f"titular-{titular.id}"]


@pytest.mark.asyncio
async def test_upload_de_extrato_sem_titular_mostra_erro_amigavel(db_session):
    fake_paperless = FakePaperlessEnvio()
    async with _client_com_paperless(db_session, fake_paperless) as client:
        resposta = await client.post(
            "/importar/extrato",
            data={"titular_id": ""},
            files={"file": ("extrato.pdf", b"%PDF-conteudo-fake", "application/pdf")},
        )

    assert resposta.status_code == 422
    assert fake_paperless.chamadas == []


@pytest.mark.asyncio
async def test_upload_de_extrato_recusa_ficheiro_que_nao_seja_pdf(db_session):
    from ava.repositories import titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.commit()

    fake_paperless = FakePaperlessEnvio()
    async with _client_com_paperless(db_session, fake_paperless) as client:
        resposta = await client.post(
            "/importar/extrato",
            data={"titular_id": str(titular.id)},
            files={"file": ("nao_e_pdf.txt", b"conteudo qualquer", "text/plain")},
        )

    mensagem = unquote(str(resposta.headers["location"]))
    assert "tem de ser um PDF" in mensagem
    assert fake_paperless.chamadas == []
