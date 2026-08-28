import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from saude.api.shared import templates
from saude.config import get_settings
from saude.db import get_session
from saude.extracao.parser_email_saude import extrair_marcacao_saude
from saude.extracao.sincronizador import SincronizadorSaude
from saude.repositories import saude_repo

import time
from saude.extracao.sincronizador_gcal import sincronizar_google_calendar_saude

router = APIRouter(tags=["dashboard"])

_ULTIMO_SYNC_GCAL = 0.0


@router.get("/")
async def dashboard_saude_page(request: Request, session: AsyncSession = Depends(get_session)):
    global _ULTIMO_SYNC_GCAL
    settings = get_settings()

    # Sincronização automática periódica com Google Calendar (a cada 5 min)
    agora_ts = time.time()
    if agora_ts - _ULTIMO_SYNC_GCAL > 300:
        try:
            await sincronizar_google_calendar_saude(session, settings.google_calendar_ical_url)
            _ULTIMO_SYNC_GCAL = agora_ts
        except Exception as e:
            pass

    perfis = await saude_repo.listar_perfis(session)
    if not perfis:
        perfis = await saude_repo.garantir_titulares_e_perfis(session)

    consultas_futuras = await saude_repo.listar_todas_consultas(session, apenas_futuras=True)
    
    # Estatísticas
    total_consultas_agendadas = len(consultas_futuras)
    total_medicamentos_ativos = sum(
        len([m for m in p.medicamentos if m.ativo]) for p in perfis
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "perfis": perfis,
            "consultas_futuras": consultas_futuras,
            "total_consultas_agendadas": total_consultas_agendadas,
            "total_medicamentos_ativos": total_medicamentos_ativos,
        },
    )


@router.get("/medicamentos")
async def medicamentos_page(request: Request, session: AsyncSession = Depends(get_session)):
    from saude.repositories.medicamento_repo import MedicamentoRepository
    repo = MedicamentoRepository(session)
    medicamentos = await repo.listar_todos()
    alertas_stock = await repo.obter_medicamentos_stock_baixo()
    prescricoes = await repo.listar_prescricoes()

    return templates.TemplateResponse(
        request,
        "medicamentos.html",
        {
            "medicamentos": medicamentos,
            "alertas_stock": alertas_stock,
            "prescricoes": prescricoes,
        },
    )


@router.post("/sincronizar")
async def sincronizar_paperless_post(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    # 1. Sincronizar Documentos do Paperless
    sync = SincronizadorSaude(settings.paperless_url, settings.paperless_token)
    await sync.sincronizar_documentos_paperless(session)

    # 2. Sincronizar Consultas do Google Calendar
    try:
        await sincronizar_google_calendar_saude(session, settings.google_calendar_ical_url)
    except Exception:
        pass

    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/importar-texto")
async def importar_texto_post(
    request: Request,
    texto_email: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    marcacao = extrair_marcacao_saude(texto_email)
    if marcacao:
        perfil = None
        if marcacao.nome_paciente:
            perfil = await saude_repo.obter_perfil_por_nome_titular(session, marcacao.nome_paciente)
        if not perfil:
            perfil = await saude_repo.obter_perfil_por_nome_titular(session, "aa-stop-run")

        if perfil:
            if marcacao.tipo == "consulta":
                await saude_repo.registar_consulta(
                    session,
                    perfil_id=perfil.id,
                    data_hora=marcacao.data_hora,
                    especialidade=marcacao.especialidade,
                    medico=marcacao.medico,
                    local_clinica=marcacao.local_clinica,
                    preparacao_instrucoes=marcacao.preparacao_instrucoes,
                    codigo_confirmacao=marcacao.codigo_confirmacao,
                )
            else:
                await saude_repo.registar_exame(
                    session,
                    perfil_id=perfil.id,
                    data=marcacao.data_hora.date(),
                    tipo_exame=marcacao.especialidade,
                    laboratorio_clinica=marcacao.local_clinica,
                    descricao=marcacao.preparacao_instrucoes,
                )

    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
