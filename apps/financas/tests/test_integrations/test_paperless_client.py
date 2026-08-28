import json

import httpx
import pytest
import respx

from ava.integrations.paperless import PaperlessClient


@pytest.mark.asyncio
@respx.mock
async def test_listar_documentos_por_tag_segue_paginacao():
    def _responder(request):
        params = dict(request.url.params)
        # Assert required parameters on both pages
        assert params.get("tags__name__iexact") == "por-estruturar", f"Expected tags__name__iexact=por-estruturar, got {params}"
        assert params.get("page_size") == "100", f"Expected page_size=100, got {params}"
        if "page" in params:
            assert params["page"] == "2", f"Expected page=2, got {params}"
            return httpx.Response(200, json={"results": [{"id": 2, "tags": [5]}], "next": None})
        return httpx.Response(
            200,
            json={
                "results": [{"id": 1, "tags": [5]}],
                "next": "http://paperless.local/api/documents/?tags__name__iexact=por-estruturar&page_size=100&page=2",
            },
        )

    respx.get("http://paperless.local/api/documents/").mock(side_effect=_responder)

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    documentos = await client.listar_documentos_por_tag("por-estruturar")
    await client.aclose()

    assert [d["id"] for d in documentos] == [1, 2]


@pytest.mark.asyncio
@respx.mock
async def test_obter_conteudo_devolve_texto_ocr():
    respx.get("http://paperless.local/api/documents/1/", params={"fields": "content"}).mock(
        return_value=httpx.Response(200, json={"content": "Total a pagar: 45,67 EUR"})
    )

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    conteudo = await client.obter_conteudo(1)
    await client.aclose()

    assert conteudo == "Total a pagar: 45,67 EUR"


@pytest.mark.asyncio
@respx.mock
async def test_remover_tag_atualiza_lista_sem_a_tag_removida():
    respx.get("http://paperless.local/api/documents/1/", params={"fields": "tags"}).mock(
        return_value=httpx.Response(200, json={"tags": [5, 9]})
    )
    patch_route = respx.patch("http://paperless.local/api/documents/1/").mock(
        return_value=httpx.Response(200, json={"tags": [9]})
    )

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    await client.remover_tag(1, tag_id=5)
    await client.aclose()

    assert patch_route.called
    sent = json.loads(patch_route.calls.last.request.content)
    assert sent == {"tags": [9]}


@pytest.mark.asyncio
@respx.mock
async def test_obter_ou_criar_tag_cria_quando_nao_existe():
    respx.get("http://paperless.local/api/tags/", params={"name__iexact": "nova-tag"}).mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    respx.post("http://paperless.local/api/tags/").mock(
        return_value=httpx.Response(201, json={"id": 55, "name": "nova-tag"})
    )

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    tag_id = await client.obter_ou_criar_tag("nova-tag")
    await client.aclose()

    assert tag_id == 55


@pytest.mark.asyncio
@respx.mock
async def test_enviar_documento_faz_upload_multipart_com_tags():
    # duas tags propositadamente: um regresso a um dict com valor escalar em vez de uma
    # lista (o bug documentado no comentário de enviar_documento) faz o multipart enviar
    # só a última tag, silenciosamente derrubando as restantes — com uma única tag esse
    # regresso passaria despercebido.
    respx.get("http://paperless.local/api/tags/", params={"name__iexact": "por-estruturar"}).mock(
        return_value=httpx.Response(200, json={"results": [{"id": 7}]})
    )
    respx.get("http://paperless.local/api/tags/", params={"name__iexact": "edp"}).mock(
        return_value=httpx.Response(200, json={"results": [{"id": 12}]})
    )
    upload_route = respx.post("http://paperless.local/api/documents/post_document/").mock(
        return_value=httpx.Response(200, text='"task-id-123"')
    )

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    await client.enviar_documento(
        conteudo=b"fake-image-bytes", nome_ficheiro="talao.jpg", tags=["por-estruturar", "edp"]
    )
    await client.aclose()

    assert upload_route.called
    corpo_enviado = upload_route.calls.last.request.content
    assert b'name="tags"\r\n\r\n7' in corpo_enviado
    assert b'name="tags"\r\n\r\n12' in corpo_enviado
    # duas partes "tags" distintas no multipart — não uma lista serializada num só campo
    assert corpo_enviado.count(b'name="tags"') == 2


@pytest.mark.asyncio
@respx.mock
async def test_obter_mapa_de_tags_devolve_dicionario_id_para_nome():
    respx.get("http://paperless.local/api/tags/", params={"page_size": "1000"}).mock(
        return_value=httpx.Response(
            200, json={"results": [{"id": 1, "name": "por-estruturar"}, {"id": 2, "name": "edp"}]}
        )
    )

    client = PaperlessClient(base_url="http://paperless.local", token="tok")
    mapa = await client.obter_mapa_de_tags()
    await client.aclose()

    assert mapa == {1: "por-estruturar", 2: "edp"}
