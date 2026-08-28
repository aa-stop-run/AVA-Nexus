import pytest

from ava.repositories.documento_repo import criar_documento, obter_por_paperless_id


@pytest.mark.asyncio
async def test_criar_e_obter_documento_por_paperless_id(db_session):
    documento = await criar_documento(
        db_session,
        paperless_document_id=42,
        nivel_extracao=0,
        dados_extraidos={"valor_total": "45.67"},
    )

    encontrado = await obter_por_paperless_id(db_session, 42)

    assert encontrado is not None
    assert encontrado.id == documento.id
    assert encontrado.estado_validacao == "pendente"
