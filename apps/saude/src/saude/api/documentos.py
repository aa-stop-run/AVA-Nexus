import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from saude.db import get_session
from saude.repositories import saude_repo

router = APIRouter(prefix="/documentos", tags=["documentos"])


@router.get("/{doc_id}/visualizar")
async def visualizar_documento(doc_id: int, session: AsyncSession = Depends(get_session)):
    """Abre o documento PDF original em modo inline na janela do navegador."""
    doc = await saude_repo.obter_documento_por_id(session, doc_id)
    if not doc or not doc.caminho_ficheiro:
        raise HTTPException(status_code=404, detail="Registo de documento não encontrado.")

    # Procurar o caminho absoluto ou alternativo
    caminho = Path(doc.caminho_ficheiro)
    if not caminho.exists():
        # Tentar no diretório de documentos relativo
        caminho_alt = Path("/app/documentos_saude") / caminho.name
        if caminho_alt.exists():
            caminho = caminho_alt
        else:
            raise HTTPException(status_code=404, detail=f"Ficheiro PDF físico não encontrado no servidor ({caminho.name}).")

    return FileResponse(
        str(caminho),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.nome_ficheiro}"'},
    )


@router.get("/{doc_id}/download")
async def descarregar_documento(doc_id: int, session: AsyncSession = Depends(get_session)):
    """Força o download do documento PDF original."""
    doc = await saude_repo.obter_documento_por_id(session, doc_id)
    if not doc or not doc.caminho_ficheiro:
        raise HTTPException(status_code=404, detail="Registo de documento não encontrado.")

    caminho = Path(doc.caminho_ficheiro)
    if not caminho.exists():
        caminho_alt = Path("/app/documentos_saude") / caminho.name
        if caminho_alt.exists():
            caminho = caminho_alt
        else:
            raise HTTPException(status_code=404, detail=f"Ficheiro PDF físico não encontrado ({caminho.name}).")

    return FileResponse(
        str(caminho),
        media_type="application/pdf",
        filename=doc.nome_ficheiro,
    )
