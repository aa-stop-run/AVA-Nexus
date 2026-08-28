from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from hub.db import get_session
from hub.services.agenda_service import (
    obter_agenda_unificada,
    criar_evento_calendario,
    atualizar_evento_calendario,
    remover_evento_calendario,
)

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


class EventoCreate(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=255)
    descricao: Optional[str] = None
    data_inicio: datetime
    data_fim: Optional[datetime] = None
    tipo: str = Field(default="pessoal")
    local: Optional[str] = None
    notificar: bool = True
    paciente: Optional[str] = None
    medico: Optional[str] = None


class EventoUpdate(BaseModel):
    titulo: Optional[str] = None
    descricao: Optional[str] = None
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None
    tipo: Optional[str] = None
    local: Optional[str] = None
    medico: Optional[str] = None


@router.get("")
async def get_agenda(
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2020, le=2040),
    session: AsyncSession = Depends(get_session),
):
    """Devolve todos os eventos unificados do ecossistema para o mês/ano solicitado."""
    return await obter_agenda_unificada(session, ano=ano, mes=mes)


@router.get("/proximos")
async def get_proximos_agenda(
    limite: int = Query(8, ge=1, le=50),
    dias_a_frente: int = Query(60, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    """Devolve os próximos eventos cronológicos da agenda (Cockpit feed)."""
    from hub.services.agenda_service import obter_proximos_eventos
    return await obter_proximos_eventos(session, limite=limite, dias_a_frente=dias_a_frente)



@router.post("/evento")
async def create_evento(
    payload: EventoCreate,
    session: AsyncSession = Depends(get_session),
):
    """Cria um novo evento pessoal ou consulta médica na agenda."""
    try:
        dados = payload.model_dump(exclude_unset=True)
        novo = await criar_evento_calendario(session, dados)
        return {"status": "ok", "evento": novo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/evento/{evento_id}")
async def update_evento(
    evento_id: str,
    payload: EventoUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Atualiza um evento existente ou consulta médica na agenda."""
    try:
        dados = payload.model_dump(exclude_unset=True)
        atualizado = await atualizar_evento_calendario(session, evento_id, dados)
        return {"status": "ok", "evento": atualizado}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/evento/{evento_id}")
async def delete_evento(
    evento_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove um evento da agenda pessoal ou desmarca consulta médica."""
    removido = await remover_evento_calendario(session, evento_id)
    if not removido:
        raise HTTPException(status_code=404, detail="Evento não encontrado ou não removível.")
    return {"status": "ok", "removido": True}


@router.post("/sync-google")
async def sync_google_endpoint():
    """Força sincronização imediata dos eventos do Google Calendar via iCal."""
    from hub.config import get_settings
    from hub.services.google_calendar_service import obter_eventos_google_calendar
    settings = get_settings()
    eventos = await obter_eventos_google_calendar(settings.google_calendar_ical_url, force_refresh=True)
    return {"status": "ok", "total_eventos_google": len(eventos)}


@router.post("/sync-paperless")
async def sync_paperless_endpoint(session: AsyncSession = Depends(get_session)):
    """Faz scan a novos documentos no Paperless e extrai bilhetes, consultas e eventos."""
    from hub.config import get_settings
    from hub.services.paperless_event_extractor import extrair_e_sincronizar_paperless
    settings = get_settings()
    resultado = await extrair_e_sincronizar_paperless(
        session=session,
        paperless_url=settings.paperless_url,
        paperless_token=settings.paperless_token
    )
    return {"status": "ok", "resultado": resultado}


@router.get("/feed.ics")
async def get_ical_feed(session: AsyncSession = Depends(get_session)):
    """Disponibiliza o feed iCal (.ics) padronizado da AVA para subscrição no Google Calendar, Apple Calendar ou Outlook."""
    from fastapi.responses import Response
    from hub.services.agenda_service import gerar_feed_ical_ava
    conteudo_ics = await gerar_feed_ical_ava(session)
    return Response(
        content=conteudo_ics,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="ava_agenda.ics"'}
    )


