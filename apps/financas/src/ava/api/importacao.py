"""Importação do ficheiro de movimentos do banco.

Substitui a rota anterior, que construía `ItemFila` com duas colunas que não existem
(`tipo_documento`, `dados_extra`) e levantava `TypeError` na primeira linha — e cujos itens, mesmo
que entrassem, nunca eram processados por nada (spec 2026-08-09, §9).
"""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.deps import get_paperless_client
from ava.db import get_session
from ava.extraction.parsers import bpi_net_movimentos
from ava.ingestion.importacao_ficheiro import importar
from ava.integrations.paperless import PaperlessClient
from ava.repositories import conta_repo, titular_repo
from ava.repositories.movimento_repo import SomaDasLinhasNaoBate, ValorNaoPositivo

router = APIRouter(tags=["importacao"])
templates = Jinja2Templates(directory="src/ava/templates")


@router.get("/importar", response_class=HTMLResponse)
async def page_importar(
    request: Request, erro: str | None = None, msg: str | None = None,
    erro_extrato: str | None = None, msg_extrato: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    contas = await conta_repo.listar_todas_ativas(session)
    titulares = await titular_repo.listar_titulares(session)
    return templates.TemplateResponse(
        request,
        "importacao.html",
        {
            "contas": contas, "erro": erro, "msg": msg,
            "titulares": titulares, "erro_extrato": erro_extrato, "msg_extrato": msg_extrato,
        },
    )


@router.post("/importar")
async def processar_importacao(
    conta_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Lê o ficheiro, importa os movimentos e regista a âncora.

    O ficheiro é verificado por inteiro antes de se gravar seja o que for: se o saldo corrente não
    fechar, nada entra. Importar metade de um ficheiro que não se explica a si próprio seria pior
    do que não importar nada.
    """
    if not (file.filename or "").lower().endswith(".xlsx"):
        return RedirectResponse(
            url="/importar?erro=" + quote("O ficheiro tem de ser o .xlsx exportado do BPI Net."),
            status_code=303,
        )

    conteudo = await file.read()
    try:
        ficheiro = bpi_net_movimentos.ler(conteudo)
    except bpi_net_movimentos.FicheiroInvalido as exc:
        return RedirectResponse(url="/importar?erro=" + quote(str(exc)), status_code=303)

    try:
        resultado = await importar(session, ficheiro, conta_id=conta_id)
        await session.commit()
    except (SomaDasLinhasNaoBate, ValorNaoPositivo) as exc:
        # Segunda linha de defesa (revisão final, achado 5): o parser já filtra as linhas de
        # valor zero conhecidas (ver bpi_net_movimentos.ler), mas esta rota não tinha tratamento
        # nenhum para o que ainda escapasse dele — um movimento assim rebentava com um 500 mudo,
        # em vez do redirect ?erro= que o resto desta rota já usa para um ficheiro inválido.
        await session.rollback()
        return RedirectResponse(
            url="/importar?erro=" + quote(f"Não foi possível importar: {exc}"), status_code=303
        )

    partes = [
        f"{resultado.criados} movimentos novos",
        f"{resultado.casados} casados com registos manuais",
        f"{resultado.saltados} já existiam",
    ]
    if resultado.cobertos_pelo_extrato:
        # Contador próprio (revisão da revisão final, minor): estas linhas nunca chegaram a
        # existir como movimento — dizer "já existiam" seria falso sobre elas. Só aparece na
        # mensagem quando há alguma, para não engordar a frase em toda importação sem extrato.
        partes.append(f"{resultado.cobertos_pelo_extrato} já cobertos pelo extrato")
    if resultado.ancora is not None:
        partes.append(
            f"saldo do banco registado: {resultado.ancora.valor} € a "
            f"{resultado.ancora.data.strftime('%d/%m/%Y')}"
        )
    return RedirectResponse(url="/importar?msg=" + quote(" · ".join(partes)), status_code=303)


@router.post("/importar/extrato")
async def processar_upload_extrato(
    titular_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    paperless: PaperlessClient = Depends(get_paperless_client),
):
    """Envia um extrato (PDF) ao Paperless com as etiquetas que o pipeline já procura.

    Não dispara processamento nenhum diretamente — o scheduler (job_ingestao, de 10 em 10
    minutos) apanha o documento sozinho, exatamente como já acontece com o que entra pela pasta
    sincronizada ou por mail. Tentar processar aqui, na hora, arriscaria o Paperless ainda não
    ter terminado o OCR do lado dele.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        return RedirectResponse(
            url="/importar?erro_extrato=" + quote("O ficheiro tem de ser um PDF."),
            status_code=303,
        )

    conteudo = await file.read()
    await paperless.enviar_documento(
        conteudo=conteudo,
        nome_ficheiro=file.filename,
        tags=["extrato-por-estruturar", f"titular-{titular_id}"],
    )

    return RedirectResponse(
        url="/importar?msg_extrato="
        + quote("Extrato enviado. É processado automaticamente nos próximos minutos."),
        status_code=303,
    )
