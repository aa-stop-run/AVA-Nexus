import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from veiculos.api.shared import templates
from veiculos.db import get_session
from veiculos.logica.prazos_ipo import calcular_proxima_ipo, verificar_estado_prazos
from veiculos.logica.consumos import calcular_medias_abastecimentos, AbastecimentoInput
from veiculos.repositories import veiculo_repo

router = APIRouter(prefix="/veiculos", tags=["veiculos"])


@router.get("/{id}")
async def veiculo_detalhe_page(
    request: Request,
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    hoje = date.today()
    v = await veiculo_repo.obter_veiculo_por_id(session, id)
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    manutencoes = await veiculo_repo.listar_manutencoes(session, id)
    abastecimentos = await veiculo_repo.listar_abastecimentos(session, id)

    # Consulta de Seguro / Contrato Associado
    contrato_seguro = None
    telefones_seguro = {
        "assistencia": "+351 309 739 806",
        "vidros": "808 211 690",
        "seguradora": "+351 218 704 900",
    }
    try:
        from sqlalchemy import text
        import re
        res_contrato = await session.execute(text("""
            SELECT c.*, f.nome as fornecedor_nome
            FROM contrato c
            LEFT JOIN fornecedor f ON f.id = c.fornecedor_id
            WHERE c.tipo = 'seguro_auto' 
              AND (
                  (c.ativo_id IS NOT NULL AND c.ativo_id = :ativo_id)
                  OR (:matricula <> '' AND (c.nome ILIKE :mat_like OR c.notas ILIKE :mat_like))
                  OR (:nome <> '' AND c.nome ILIKE :nome_like)
              )
            ORDER BY c.data_fim DESC NULLS LAST
            LIMIT 1;
        """), {
            "ativo_id": v.ativo_id,
            "matricula": v.matricula or "",
            "mat_like": f"%{v.matricula}%" if v.matricula else "",
            "nome": v.nome or "",
            "nome_like": f"%{v.nome}%" if v.nome else "",
        })
        row = res_contrato.mappings().first()
        if row:
            contrato_seguro = dict(row)
            notas = contrato_seguro.get("notas") or ""
            m_assist = re.search(r"Assist[êe]ncia.*?:\s*([+\d\s]{9,16})", notas, re.IGNORECASE)
            if m_assist:
                telefones_seguro["assistencia"] = m_assist.group(1).strip()
            m_vidros = re.search(r"Vidros.*?:\s*([\d\s]{9,12})", notas, re.IGNORECASE)
            if m_vidros:
                telefones_seguro["vidros"] = m_vidros.group(1).strip()
            m_seg = re.search(r"Telefone Insurance Co..*?:\s*([+\d\s]{9,16})", notas, re.IGNORECASE)
            if m_seg:
                telefones_seguro["seguradora"] = m_seg.group(1).strip()
    except Exception as e:
        print(f"Erro ao obter contrato de seguro para veículo: {e}")

    # Prazos
    data_fim_seg = v.data_fim_seguro or (contrato_seguro.get("data_fim") if contrato_seguro else None)
    data_ipo = v.data_proxima_ipo or calcular_proxima_ipo(
        ano_matricula=v.ano_matricula,
        mes_matricula=v.mes_matricula,
        tipo=v.tipo,
        referencia=hoje,
    )
    estado_prazos = verificar_estado_prazos(
        data_proxima_ipo=data_ipo,
        mes_matricula_iuc=v.mes_matricula,
        data_fim_seguro=data_fim_seg,
        hoje=hoje,
    )

    # Estatísticas de Consumo
    abast_inputs = [
        AbastecimentoInput(
            data=ab.data,
            km=ab.km,
            quantidade=ab.quantidade,
            preco_total=ab.preco_total,
            tanque_cheio=ab.tanque_cheio,
        )
        for ab in abastecimentos
    ]
    stats_consumo = calcular_medias_abastecimentos(abast_inputs)
    total_gasto_manutencoes = sum((m.custo for m in manutencoes), Decimal("0.00"))

    return templates.TemplateResponse(
        request,
        "veiculo_detalhe.html",
        {
            "veiculo": v,
            "manutencoes": manutencoes,
            "abastecimentos": abastecimentos,
            "data_proxima_ipo": data_ipo,
            "estado_prazos": estado_prazos,
            "stats_consumo": stats_consumo,
            "total_gasto_manutencoes": total_gasto_manutencoes,
            "contrato_seguro": contrato_seguro,
            "telefones_seguro": telefones_seguro,
        },
    )


@router.post("/{id}/editar")
async def editar_veiculo_post(
    request: Request,
    id: uuid.UUID,
    nome: str = Form(...),
    tipo: str = Form("carro"),
    matricula: str | None = Form(None),
    ano_matricula: int | None = Form(None),
    mes_matricula: int | None = Form(None),
    combustivel: str = Form("gasoleo"),
    km_atual: int = Form(0),
    data_proxima_ipo: date | None = Form(None),
    seguradora: str | None = Form(None),
    numero_apolice: str | None = Form(None),
    data_fim_seguro: date | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await veiculo_repo.atualizar_veiculo(
        session,
        id,
        nome=nome,
        tipo=tipo,
        matricula=matricula,
        ano_matricula=ano_matricula,
        mes_matricula=mes_matricula,
        combustivel=combustivel,
        km_atual=km_atual,
        data_proxima_ipo=data_proxima_ipo,
        seguradora=seguradora,
        numero_apolice=numero_apolice,
        data_fim_seguro=data_fim_seguro,
    )
    return RedirectResponse(f"/veiculos/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/apagar")
async def apagar_veiculo_post(
    request: Request,
    id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await veiculo_repo.apagar_veiculo(session, id)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/manutencoes")
async def registar_manutencao_post(
    request: Request,
    id: uuid.UUID,
    data: date = Form(...),
    km: int = Form(...),
    tipo_servico: str = Form(...),
    descricao: str = Form(...),
    oficina: str | None = Form(None),
    custo: str = Form("0.00"),
    proxima_revisao_km: int | None = Form(None),
    proxima_revisao_data: date | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    try:
        custo_dec = Decimal(custo.replace(",", "."))
    except Exception:
        custo_dec = Decimal("0.00")

    m = await veiculo_repo.registar_manutencao(
        session,
        veiculo_id=id,
        data=data,
        km=km,
        tipo_servico=tipo_servico,
        descricao=descricao,
        oficina=oficina,
        custo=custo_dec,
        proxima_revisao_km=proxima_revisao_km,
        proxima_revisao_data=proxima_revisao_data,
    )

    if "HX-Request" in request.headers:
        return templates.TemplateResponse(
            request,
            "_manutencao_linha.html",
            {"m": m},
        )
    return RedirectResponse(f"/veiculos/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{id}/abastecimentos")
async def registar_abastecimento_post(
    request: Request,
    id: uuid.UUID,
    data: date = Form(...),
    km: int = Form(...),
    quantidade: str = Form(...),
    preco_total: str = Form(...),
    posto: str | None = Form(None),
    tanque_cheio: bool = Form(True),
    session: AsyncSession = Depends(get_session),
):
    try:
        qtd_dec = Decimal(quantidade.replace(",", "."))
        preco_dec = Decimal(preco_total.replace(",", "."))
    except Exception:
        qtd_dec = Decimal("0.00")
        preco_dec = Decimal("0.00")

    await veiculo_repo.registar_abastecimento(
        session,
        veiculo_id=id,
        data=data,
        km=km,
        quantidade=qtd_dec,
        preco_total=preco_dec,
        posto=posto,
        tanque_cheio=tanque_cheio,
    )

    return RedirectResponse(f"/veiculos/{id}", status_code=status.HTTP_303_SEE_OTHER)
