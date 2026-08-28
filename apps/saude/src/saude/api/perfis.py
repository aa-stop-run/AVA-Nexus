import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from saude.api.shared import templates
from saude.config import get_settings
from saude.db import get_session
from saude.extracao.parser_biomarcadores import (
    extrair_biomarcadores,
    extrair_data_relatorio,
    extrair_texto_de_pdf,
    extrair_laboratorio,
    extrair_titular_sugerido,
)
from saude.repositories import saude_repo

router = APIRouter(prefix="/perfis", tags=["perfis"])


def _obter_dir_documentos() -> Path:
    env_dir = os.getenv("DOCUMENTOS_DIR")
    if env_dir:
        p = Path(env_dir)
    else:
        p = Path("/app/documentos_saude")
        if not p.exists():
            p = Path("documentos_saude")
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _enviar_para_paperless(conteudo_bytes: bytes, nome_ficheiro: str) -> None:
    settings = get_settings()
    if not settings.paperless_url or not settings.paperless_token:
        return
    try:
        async with httpx.AsyncClient(base_url=settings.paperless_url, headers={"Authorization": f"Token {settings.paperless_token}"}, timeout=8.0) as client:
            files = {"document": (nome_ficheiro, conteudo_bytes, "application/pdf")}
            data = {"title": nome_ficheiro}
            await client.post("/api/documents/post_document/", files=files, data=data)
    except Exception as e:
        print(f"Aviso Paperless: {e}")



@router.get("/{id}")
async def perfil_detalhe_page(
    request: Request,
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    p = await saude_repo.obter_perfil_por_id(session, id)
    if not p:
        raise HTTPException(status_code=404, detail="Perfil de saúde não encontrado")

    insights = await saude_repo.gerar_insights_biomarcadores(session, id)
    
    # Parâmetros únicos disponíveis para o gráfico, priorizando marcadores frequentes
    prioritarios = [
        "Glicémia",
        "Triglicéridos",
        "Colesterol Total",
        "Colesterol HDL",
        "Colesterol LDL",
        "Hemoglobina",
        "Leucócitos",
        "Plaquetas",
        "Ureia",
        "Creatinina",
        "Ácido Úrico",
        "TGO (AST)",
        "TGP (ALT)",
        "GGT",
        "Ferritina",
        "Vitamina D",
        "TSH",
        "FT4",
        "Sódio",
        "Potássio",
        "Cloro",
    ]
    todos_params = list({b.parametro for b in p.biomarcadores})
    parametros_disponiveis = [item for item in prioritarios if item in todos_params] + sorted(
        [item for item in todos_params if item not in prioritarios]
    )

    # Agrupar biomarcadores por análise/sessão de exame (data + lab + doc_id)
    sessoes_dict = {}
    for b in p.biomarcadores:
        chave = (b.data, b.documento_id, b.laboratorio or "Laboratório Clínico")
        if chave not in sessoes_dict:
            sessoes_dict[chave] = {
                "id": f"sessao_{b.data.strftime('%Y%m%d')}_{b.documento_id or 0}",
                "data": b.data,
                "documento_id": b.documento_id,
                "laboratorio": b.laboratorio or "Laboratório Clínico",
                "biomarcadores": [],
                "normais": 0,
                "alterados": 0,
            }
        sessoes_dict[chave]["biomarcadores"].append(b)
        if b.estado in ("alto", "baixo"):
            sessoes_dict[chave]["alterados"] += 1
        else:
            sessoes_dict[chave]["normais"] += 1

    sessoes_analises = sorted(sessoes_dict.values(), key=lambda s: s["data"], reverse=True)
    for s in sessoes_analises:
        s["biomarcadores"].sort(key=lambda b: (b.categoria, b.parametro))

    return templates.TemplateResponse(
        request,
        "perfil_detalhe.html",
        {
            "perfil": p,
            "insights": insights,
            "parametros_disponiveis": parametros_disponiveis,
            "sessoes_analises": sessoes_analises,
        },
    )


@router.post("/{id}/editar")
async def editar_perfil_post(
    request: Request,
    id: uuid.UUID,
    numero_utente_sns: str | None = Form(None),
    data_nascimento: date | None = Form(None),
    grupo_sanguineo: str | None = Form(None),
    alergias: str | None = Form(None),
    condicoes_cronicas: str | None = Form(None),
    notas: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await saude_repo.atualizar_perfil(
        session,
        id,
        numero_utente_sns=numero_utente_sns,
        data_nascimento=data_nascimento,
        grupo_sanguineo=grupo_sanguineo,
        alergias=alergias,
        condicoes_cronicas=condicoes_cronicas,
        notas=notas,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/consultas")
async def criar_consulta_post(
    request: Request,
    id: uuid.UUID,
    data: date = Form(...),
    hora: str = Form("09:00"),
    especialidade: str = Form(...),
    medico: str | None = Form(None),
    local_clinica: str | None = Form(None),
    motivo: str | None = Form(None),
    preparacao_instrucoes: str | None = Form(None),
    custo: str = Form("0.00"),
    session: AsyncSession = Depends(get_session),
):
    try:
        h, m = map(int, hora.split(":"))
        dt = datetime(data.year, data.month, data.day, h, m, tzinfo=timezone.utc)
    except Exception:
        dt = datetime(data.year, data.month, data.day, 9, 0, tzinfo=timezone.utc)

    try:
        custo_dec = Decimal(custo.replace(",", "."))
    except Exception:
        custo_dec = Decimal("0.00")

    await saude_repo.registar_consulta(
        session,
        perfil_id=id,
        data_hora=dt,
        especialidade=especialidade,
        medico=medico,
        local_clinica=local_clinica,
        motivo=motivo,
        preparacao_instrucoes=preparacao_instrucoes,
        custo=custo_dec,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/exames")
async def criar_exame_post(
    request: Request,
    id: uuid.UUID,
    data: date = Form(...),
    tipo_exame: str = Form(...),
    laboratorio_clinica: str | None = Form(None),
    descricao: str | None = Form(None),
    resultados_resumo: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await saude_repo.registar_exame(
        session,
        perfil_id=id,
        data=data,
        tipo_exame=tipo_exame,
        laboratorio_clinica=laboratorio_clinica,
        descricao=descricao,
        resultados_resumo=resultados_resumo,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/medicamentos")
async def criar_medicamento_post(
    request: Request,
    id: uuid.UUID,
    nome: str = Form(...),
    dosagem: str | None = Form(None),
    posologia: str | None = Form(None),
    data_inicio: date | None = Form(None),
    data_fim: date | None = Form(None),
    notas: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await saude_repo.registar_medicamento(
        session,
        perfil_id=id,
        nome=nome,
        dosagem=dosagem,
        posologia=posologia,
        data_inicio=data_inicio,
        data_fim=data_fim,
        ativo=True,
        notas=notas,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/vacinas")
async def criar_vacina_post(
    request: Request,
    id: uuid.UUID,
    nome_vacina: str = Form(...),
    data_toma: date = Form(...),
    proxima_dose_data: date | None = Form(None),
    lote_local: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await saude_repo.registar_vacina(
        session,
        perfil_id=id,
        nome_vacina=nome_vacina,
        data_toma=data_toma,
        proxima_dose_data=proxima_dose_data,
        lote_local=lote_local,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/biomarcadores")
async def criar_biomarcador_post(
    request: Request,
    id: uuid.UUID,
    data: date = Form(...),
    parametro: str = Form(...),
    valor: str = Form(...),
    unidade: str = Form("mg/dL"),
    categoria: str = Form("Geral"),
    valor_referencia_min: str | None = Form(None),
    valor_referencia_max: str | None = Form(None),
    laboratorio: str | None = Form(None),
    notas: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    val_dec = Decimal(valor.replace(",", "."))
    min_dec = Decimal(valor_referencia_min.replace(",", ".")) if valor_referencia_min else None
    max_dec = Decimal(valor_referencia_max.replace(",", ".")) if valor_referencia_max else None

    await saude_repo.registar_biomarcador(
        session,
        perfil_id=id,
        data=data,
        parametro=parametro,
        valor=val_dec,
        unidade=unidade,
        categoria=categoria,
        valor_referencia_min=min_dec,
        valor_referencia_max=max_dec,
        laboratorio=laboratorio,
        notas=notas,
    )
    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/upload-analises")
async def upload_analises_pdf_post(
    request: Request,
    id: uuid.UUID,
    ficheiro: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    conteudo_bytes = await ficheiro.read()
    if not conteudo_bytes:
        return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)

    texto = extrair_texto_de_pdf(conteudo_bytes)
    data_exame = extrair_data_relatorio(texto) if texto else date.today()
    lab_nome = extrair_laboratorio(texto) if texto else "Laboratório Clínico"

    # 1. Save ficheiro físico permanentemente
    doc_dir = _obter_dir_documentos()
    nome_limpo = f"doc_{uuid.uuid4().hex[:8]}_{ficheiro.filename or 'analises.pdf'}"
    caminho_final = doc_dir / nome_limpo
    with open(caminho_final, "wb") as f:
        f.write(conteudo_bytes)

    # 2. Registar na tabela documento_saude
    novo_doc = await saude_repo.registar_documento_saude(
        session,
        perfil_id=id,
        nome_ficheiro=ficheiro.filename or "Análises Clínicas.pdf",
        caminho_ficheiro=str(caminho_final),
        tamanho_bytes=len(conteudo_bytes),
        data_documento=data_exame,
        laboratorio_clinica=lab_nome,
    )

    # 3. Extrair e registar biomarcadores vinculados a este documento
    if texto:
        biomarcadores = extrair_biomarcadores(texto)
        for b in biomarcadores:
            await saude_repo.registar_biomarcador(
                session,
                perfil_id=id,
                data=data_exame,
                parametro=b.parametro,
                valor=b.valor,
                unidade=b.unidade,
                categoria=b.categoria,
                valor_referencia_min=b.ref_min,
                valor_referencia_max=b.ref_max,
                laboratorio=lab_nome,
                documento_id=novo_doc.id,
            )

    # 4. Enviar cópia de arquivo para o Paperless em background
    try:
        await _enviar_para_paperless(conteudo_bytes, novo_doc.nome_ficheiro)
    except Exception:
        pass

    return RedirectResponse(f"/perfis/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{id}/biomarcadores/grafico-dados")
async def obter_dados_grafico_biomarcador(
    id: uuid.UUID,
    parametro: str,
    session: AsyncSession = Depends(get_session),
):
    historico = await saude_repo.obter_historico_biomarcador(session, id, parametro)
    if not historico:
        return JSONResponse({"labels": [], "valores": [], "ref_min": None, "ref_max": None, "unidade": ""})

    labels = [b.data.strftime("%d/%m/%Y") for b in historico]
    valores = [float(b.valor) for b in historico]
    ref_min = float(historico[-1].valor_referencia_min) if historico[-1].valor_referencia_min is not None else None
    ref_max = float(historico[-1].valor_referencia_max) if historico[-1].valor_referencia_max is not None else None
    unidade = historico[-1].unidade

    return JSONResponse({
        "labels": labels,
        "valores": valores,
        "ref_min": ref_min,
        "ref_max": ref_max,
        "unidade": unidade,
    })


@router.get("/{id}/biomarcadores/grafico-multi")
async def obter_dados_grafico_multi_biomarcadores(
    id: uuid.UUID,
    parametros: str,
    session: AsyncSession = Depends(get_session),
):
    """Retorna dados normalizados para visualização multi-parâmetro simultânea (ex: Painel Lipídico)."""
    lista_params = [p.strip() for p in parametros.split(",") if p.strip()]
    if not lista_params:
        return JSONResponse({"labels": [], "datasets": []})

    # Cores pré-definidas para gráficos comparativos
    cores = [
        {"border": "#0284c7", "bg": "rgba(2, 132, 199, 0.1)"},
        {"border": "#10b981", "bg": "rgba(16, 185, 129, 0.1)"},
        {"border": "#f43f5e", "bg": "rgba(244, 63, 94, 0.1)"},
        {"border": "#f59e0b", "bg": "rgba(245, 158, 11, 0.1)"},
        {"border": "#8b5cf6", "bg": "rgba(139, 92, 246, 0.1)"},
    ]

    # Obter datas de todos os parâmetros para unificar o eixo X
    mapa_por_param = {}
    todas_datas = set()

    for p in lista_params:
        hist = await saude_repo.obter_historico_biomarcador(session, id, p)
        mapa_por_param[p] = {b.data: float(b.valor) for b in hist}
        for b in hist:
            todas_datas.add(b.data)

    datas_ordenadas = sorted(list(todas_datas))
    labels = [d.strftime("%d/%m/%Y") for d in datas_ordenadas]

    datasets = []
    for idx, p in enumerate(lista_params):
        cor = cores[idx % len(cores)]
        valores = [mapa_por_param[p].get(d, None) for d in datas_ordenadas]
        datasets.append({
            "label": p,
            "data": valores,
            "borderColor": cor["border"],
            "backgroundColor": cor["bg"],
            "borderWidth": 2.5,
            "pointRadius": 4,
            "pointHoverRadius": 6,
            "fill": False,
            "tension": 0.2,
            "spanGaps": True,
        })

    return JSONResponse({
        "labels": labels,
        "datasets": datasets,
    })

