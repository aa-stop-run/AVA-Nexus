import pytest
from datetime import date, datetime, timezone
from decimal import Decimal
from httpx import ASGITransport, AsyncClient

from saude.main import create_app
from saude.db import get_session
from saude.repositories import saude_repo


@pytest.fixture
def app(db_session):
    app_instance = create_app()

    async def override_get_session():
        yield db_session

    app_instance.dependency_overrides[get_session] = override_get_session
    return app_instance


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_dashboard_saude(client, db_session):
    await saude_repo.garantir_titulares_e_perfis(db_session)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Saúde Familiar" in resp.text
    assert "aa-stop-run" in resp.text
    assert "Member" in resp.text
    assert "Junior" in resp.text


@pytest.mark.asyncio
async def test_get_perfil_e_adicionar_consulta(client, db_session):
    perfis = await saude_repo.garantir_titulares_e_perfis(db_session)
    perfil_alex = next(p for p in perfis if p.titular.nome == "aa-stop-run")

    resp_get = await client.get(f"/perfis/{perfil_alex.id}")
    assert resp_get.status_code == 200
    assert "Health Dossier" in resp_get.text

    resp_post = await client.post(
        f"/perfis/{perfil_alex.id}/consultas",
        data={
            "data": "2026-10-15",
            "hora": "10:30",
            "especialidade": "Oftalmologia",
            "medico": "Dr. Santos",
            "local_clinica": "CUF Descobertas",
            "motivo": "Rotina",
            "custo": "75.00",
        },
        follow_redirects=False,
    )
    assert resp_post.status_code in (200, 302, 303)


@pytest.mark.asyncio
async def test_importar_texto_email_endpoint(client, db_session):
    await saude_repo.garantir_titulares_e_perfis(db_session)
    texto = "Marcação para Junior: Consulta de Pediatria no Centro de Saúde dia 05/11/2026 às 11:15 com Drª Teresa Ramos."
    resp = await client.post(
        "/importar-texto",
        data={"texto_email": texto},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302, 303)
    consultas = await saude_repo.listar_todas_consultas(db_session)
    assert any(c.especialidade == "Pediatria" for c in consultas)


@pytest.mark.asyncio
async def test_biomarcadores_e_grafico_endpoint(client, db_session):
    perfis = await saude_repo.garantir_titulares_e_perfis(db_session)
    perfil_alex = next(p for p in perfis if p.titular.nome == "aa-stop-run")

    # Regista 2 leituras de Colesterol LDL para testar a variação
    resp_post1 = await client.post(
        f"/perfis/{perfil_alex.id}/biomarcadores",
        data={
            "data": "2025-11-10",
            "parametro": "Colesterol LDL",
            "valor": "120.0",
            "unidade": "mg/dL",
            "categoria": "Perfil Lipídico",
            "valor_referencia_max": "115.0",
        },
        follow_redirects=False,
    )
    assert resp_post1.status_code in (200, 302, 303)

    resp_post2 = await client.post(
        f"/perfis/{perfil_alex.id}/biomarcadores",
        data={
            "data": "2026-04-12",
            "parametro": "Colesterol LDL",
            "valor": "102.0",
            "unidade": "mg/dL",
            "categoria": "Perfil Lipídico",
            "valor_referencia_max": "115.0",
        },
        follow_redirects=False,
    )
    assert resp_post2.status_code in (200, 302, 303)

    # Verifica o endpoint de dados para o gráfico
    resp_chart = await client.get(f"/perfis/{perfil_alex.id}/biomarcadores/grafico-dados?parametro=Colesterol%20LDL")
    assert resp_chart.status_code == 200
    dados = resp_chart.json()
    assert len(dados["labels"]) == 2
    assert dados["valores"] == [120.0, 102.0]
    assert dados["ref_max"] == 115.0

    # Verifica o render da página com o insight de descida
    resp_page = await client.get(f"/perfis/{perfil_alex.id}")
    assert resp_page.status_code == 200
    assert "Colesterol LDL" in resp_page.text
    assert "Desceu" in resp_page.text


@pytest.mark.asyncio
async def test_documento_visualizar_e_download(client, db_session, tmp_path):
    from saude.models.perfil import PerfilSaude
    from saude.models.titular import Titular
    from saude.repositories import saude_repo
    from datetime import date

    titular = Titular(nome="Teste Doc")
    db_session.add(titular)
    await db_session.flush()

    perfil = PerfilSaude(titular_id=titular.id)
    db_session.add(perfil)
    await db_session.commit()

    # Criar ficheiro temporário
    pdf_file = tmp_path / "teste_analises.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy content")

    doc = await saude_repo.registar_documento_saude(
        db_session,
        perfil_id=perfil.id,
        nome_ficheiro="teste_analises.pdf",
        caminho_ficheiro=str(pdf_file),
        tamanho_bytes=len(pdf_file.read_bytes()),
        data_documento=date(2025, 7, 29),
        laboratorio_clinica="Laboratório Teste",
    )

    resp_view = await client.get(f"/documentos/{doc.id}/visualizar")
    assert resp_view.status_code == 200
    assert resp_view.headers["content-type"] == "application/pdf"
    assert "inline" in resp_view.headers.get("content-disposition", "")

    resp_down = await client.get(f"/documentos/{doc.id}/download")
    assert resp_down.status_code == 200
    assert "attachment" in resp_down.headers.get("content-disposition", "")

