import httpx


class PaperlessClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Token {token}"},
            timeout=30.0,
        )

    async def listar_documentos_por_tag(self, tag: str) -> list[dict]:
        documentos: list[dict] = []
        url = "/api/documents/"
        params: dict[str, object] | None = {"tags__name__iexact": tag, "page_size": "100"}
        while url:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            documentos.extend(payload["results"])
            url = payload.get("next")
            params = None  # `next` already carries the full query string
        return documentos

    async def obter_conteudo(self, document_id: int) -> str:
        response = await self._client.get(f"/api/documents/{document_id}/", params={"fields": "content"})
        response.raise_for_status()
        return response.json()["content"]

    async def obter_id_de_tag(self, nome: str) -> int:
        response = await self._client.get("/api/tags/", params={"name__iexact": nome})
        response.raise_for_status()
        resultados = response.json()["results"]
        if not resultados:
            raise ValueError(f"tag '{nome}' não existe no paperless")
        return resultados[0]["id"]

    async def remover_tag(self, document_id: int, tag_id: int) -> None:
        response = await self._client.get(f"/api/documents/{document_id}/", params={"fields": "tags"})
        response.raise_for_status()
        tags_atuais: list[int] = response.json()["tags"]
        novas_tags = [t for t in tags_atuais if t != tag_id]
        response = await self._client.patch(f"/api/documents/{document_id}/", json={"tags": novas_tags})
        response.raise_for_status()

    async def obter_ou_criar_tag(self, nome: str) -> int:
        response = await self._client.get("/api/tags/", params={"name__iexact": nome})
        response.raise_for_status()
        resultados = response.json()["results"]
        if resultados:
            return resultados[0]["id"]
        response = await self._client.post("/api/tags/", json={"name": nome})
        response.raise_for_status()
        return response.json()["id"]

    async def enviar_documento(
        self, *, conteudo: bytes, nome_ficheiro: str, tags: list[str] | None = None
    ) -> None:
        tag_ids = [await self.obter_ou_criar_tag(nome_tag) for nome_tag in (tags or [])]
        # `data` tem de ser um dict (não uma list[tuple]) — com httpx 0.28 uma list[tuple]
        # combinada com `files` produz um IteratorByteStream síncrono em vez de assíncrono,
        # e o AsyncClient rejeita-o com "Attempted to send a sync request with an AsyncClient
        # instance". Um dict com uma lista de valores para "tags" gera multipart async correto.
        campos: dict[str, str | list[str]] = {"title": nome_ficheiro}
        if tag_ids:
            campos["tags"] = [str(tag_id) for tag_id in tag_ids]
        ficheiros = {"document": (nome_ficheiro, conteudo)}
        response = await self._client.post("/api/documents/post_document/", data=campos, files=ficheiros)
        response.raise_for_status()

    async def obter_mapa_de_tags(self) -> dict[int, str]:
        response = await self._client.get("/api/tags/", params={"page_size": 1000})
        response.raise_for_status()
        return {tag["id"]: tag["name"] for tag in response.json()["results"]}

    async def aclose(self) -> None:
        await self._client.aclose()
