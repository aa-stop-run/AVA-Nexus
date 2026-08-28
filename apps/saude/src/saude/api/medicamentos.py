from datetime import date, datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from saude.db import get_session
from saude.repositories.medicamento_repo import MedicamentoRepository

router = APIRouter(prefix="/api/saude/medicamentos", tags=["Medicamentos & Farmácia"])


class HorarioSchema(BaseModel):
    hora: str  # '08:30'
    quantidade_dose: float = 1.0
    dias_semana: str = "todos"
    ativo: bool = True


class MedicamentoCreateSchema(BaseModel):
    titular: str
    nome: str
    dosagem: str
    principio_ativo: str | None = None
    forma_farmaceutica: str = "pill"
    stock_atual: int = 0
    stock_minimo_alerta: int = 7
    unidade_medida: str = "pills"
    instrucoes_toma: str | None = None
    medico_prescritor: str | None = None
    horarios: list[HorarioSchema] = []


class TomaRequestSchema(BaseModel):
    data_hora_prevista: datetime | None = None
    data_hora_tomada: datetime | None = None
    registado_via: str = "mobile_notification"
    observacoes: str | None = None
    quantidade_dose: float | None = None


class ReporStockRequestSchema(BaseModel):
    quantidade: int


class PrescricaoCreateSchema(BaseModel):
    titular: str
    numero_receita_sns: str | None = None
    codigo_acesso: str | None = None
    codigo_opcao: str | None = None
    data_emissao: date | None = None
    data_validade: date | None = None
    medico_prescritor: str | None = None
    especialidade: str | None = None
    notas: str | None = None


@router.get("")
async def listar_medicamentos(
    titular: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    repo = MedicamentoRepository(session)
    meds = await repo.listar_por_titular(titular)
    resultado = []
    for m in meds:
        doses_dia = sum(float(h.quantidade_dose) for h in m.horarios if h.ativo) if m.horarios else 1.0
        dias_autonomia = int(m.stock_atual / (doses_dia or 1.0))
        resultado.append({
            "id": m.id,
            "titular": m.titular,
            "nome": m.nome,
            "principio_ativo": m.principio_ativo,
            "dosagem": m.dosagem,
            "forma_farmaceutica": m.forma_farmaceutica,
            "stock_atual": m.stock_atual,
            "stock_minimo_alerta": m.stock_minimo_alerta,
            "unidade_medida": m.unidade_medida,
            "dias_autonomia": dias_autonomia,
            "ativo": m.ativo,
            "instrucoes_toma": m.instrucoes_toma,
            "medico_prescritor": m.medico_prescritor,
            "horarios": [
                {
                    "id": h.id,
                    "hora": h.hora,
                    "quantidade_dose": float(h.quantidade_dose),
                    "dias_semana": h.dias_semana,
                    "ativo": h.ativo,
                }
                for h in m.horarios
            ],
            "total_registos_toma": len(m.registos_toma),
        })
    return resultado


@router.post("", status_code=status.HTTP_201_CREATED)
async def criar_medicamento(
    payload: MedicamentoCreateSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    repo = MedicamentoRepository(session)
    med = await repo.criar_medicamento(
        titular=payload.titular,
        nome=payload.nome,
        dosagem=payload.dosagem,
        stock_atual=payload.stock_atual,
        stock_minimo_alerta=payload.stock_minimo_alerta,
        principio_ativo=payload.principio_ativo,
        forma_farmaceutica=payload.forma_farmaceutica,
        unidade_medida=payload.unidade_medida,
        instrucoes_toma=payload.instrucoes_toma,
        medico_prescritor=payload.medico_prescritor,
        horarios=[h.model_dump() for h in payload.horarios],
    )
    return {
        "id": med.id,
        "titular": med.titular,
        "nome": med.nome,
        "dosagem": med.dosagem,
        "stock_atual": med.stock_atual,
        "stock_minimo_alerta": med.stock_minimo_alerta,
        "ativo": med.ativo,
    }


@router.post("/{medicamento_id}/toma")
async def registar_toma(
    medicamento_id: int,
    payload: TomaRequestSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    repo = MedicamentoRepository(session)
    try:
        registo = await repo.registar_toma(
            medicamento_id=medicamento_id,
            data_hora_prevista=payload.data_hora_prevista,
            data_hora_tomada=payload.data_hora_tomada,
            registado_via=payload.registado_via,
            observacoes=payload.observacoes,
            quantidade_dose=payload.quantidade_dose,
        )
        med = await repo.obter_por_id(medicamento_id)
        return {
            "registo_id": registo.id,
            "medicamento_id": medicamento_id,
            "estado": registo.estado,
            "stock_atual": med.stock_atual if med else 0,
            "mensagem": f"Toma de {med.nome if med else 'medicamento'} registada com sucesso.",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{medicamento_id}/repor-stock")
async def repor_stock(
    medicamento_id: int,
    payload: ReporStockRequestSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    repo = MedicamentoRepository(session)
    try:
        med = await repo.repor_stock(medicamento_id, payload.quantidade)
        return {
            "medicamento_id": med.id,
            "stock_atual": med.stock_atual,
            "mensagem": f"Stock de {med.nome} atualizado para {med.stock_atual} unidades.",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/schedule-sync")
async def obter_schedule_sync(
    dias: int = Query(7, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    repo = MedicamentoRepository(session)
    return await repo.obter_schedule_sync(dias=dias)


@router.get("/alertas-stock")
async def obter_alertas_stock(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    repo = MedicamentoRepository(session)
    return await repo.obter_medicamentos_stock_baixo()


@router.get("/prescricoes")
async def listar_prescricoes(
    titular: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    repo = MedicamentoRepository(session)
    prescricoes = await repo.listar_prescricoes(titular)
    return [
        {
            "id": p.id,
            "titular": p.titular,
            "numero_receita_sns": p.numero_receita_sns,
            "codigo_acesso": p.codigo_acesso,
            "codigo_opcao": p.codigo_opcao,
            "data_emissao": p.data_emissao.isoformat() if p.data_emissao else None,
            "data_validade": p.data_validade.isoformat() if p.data_validade else None,
            "medico_prescritor": p.medico_prescritor,
            "especialidade": p.especialidade,
            "estado": p.estado,
            "notas": p.notas,
        }
        for p in prescricoes
    ]


@router.post("/prescricoes", status_code=status.HTTP_201_CREATED)
async def criar_prescricao(
    payload: PrescricaoCreateSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    repo = MedicamentoRepository(session)
    p = await repo.criar_prescricao(
        titular=payload.titular,
        numero_receita_sns=payload.numero_receita_sns,
        codigo_acesso=payload.codigo_acesso,
        codigo_opcao=payload.codigo_opcao,
        data_emissao=payload.data_emissao,
        data_validade=payload.data_validade,
        medico_prescritor=payload.medico_prescritor,
        especialidade=payload.especialidade,
        notas=payload.notas,
    )
    return {
        "id": p.id,
        "titular": p.titular,
        "numero_receita_sns": p.numero_receita_sns,
        "estado": p.estado,
    }
