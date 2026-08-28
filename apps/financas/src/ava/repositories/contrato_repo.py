import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ava.models.contrato import Contrato

TIPO_LABELS = {
    "seguro_auto": "Seguro Automóvel",
    "seguro_habitacao": "Seguro Habitação / Multirriscos",
    "seguro_saude": "Seguro de Saúde",
    "seguro_vida": "Seguro de Vida",
    "telecomunicacoes": "Telecomunicações",
    "energia": "Energia / Gás",
    "garantia": "Garantia de Equipamento",
    "subscricao": "Subscrição / Serviços",
    "outro": "Outro Contrato",
}

PERIODICIDADE_LABELS = {
    "mensal": "Mensal",
    "anual": "Anual",
    "trimestral": "Trimestral",
    "semestral": "Semestral",
    "unica": "Pontual / Única",
}


def calcular_valor_anualizado(valor: Decimal | None, periodicidade: str) -> Decimal:
    if valor is None or valor <= Decimal("0"):
        return Decimal("0")
    if periodicidade == "mensal":
        return valor * Decimal("12")
    if periodicidade == "trimestral":
        return valor * Decimal("4")
    if periodicidade == "semestral":
        return valor * Decimal("2")
    if periodicidade == "anual":
        return valor
    return Decimal("0")


async def criar_contrato(
    session: AsyncSession,
    *,
    titular_id: uuid.UUID,
    nome: str,
    tipo: str,
    data_inicio: date,
    data_fim: date | None = None,
    ativo_id: uuid.UUID | None = None,
    fornecedor_id: uuid.UUID | None = None,
    numero_referencia: str | None = None,
    renovacao_automatica: bool = True,
    dias_aviso_previo: int = 30,
    valor: Decimal | None = None,
    periodicidade: str = "mensal",
    documento_id: uuid.UUID | None = None,
    notas: str | None = None,
) -> Contrato:
    contrato = Contrato(
        titular_id=titular_id,
        ativo_id=ativo_id,
        fornecedor_id=fornecedor_id,
        nome=nome.strip(),
        tipo=tipo,
        numero_referencia=numero_referencia.strip() if numero_referencia else None,
        data_inicio=data_inicio,
        data_fim=data_fim,
        renovacao_automatica=renovacao_automatica,
        dias_aviso_previo=dias_aviso_previo,
        valor=valor,
        periodicidade=periodicidade,
        documento_id=documento_id,
        notas=notas.strip() if notas else None,
        ativo=True,
    )
    session.add(contrato)
    await session.flush()
    return contrato


async def obter_por_id(session: AsyncSession, contrato_id: uuid.UUID) -> Contrato | None:
    return await session.get(Contrato, contrato_id)


async def listar_todos(
    session: AsyncSession,
    *,
    apenas_ativos: bool = True,
    tipo: str | None = None,
    titular_id: uuid.UUID | None = None,
    ativo_id: uuid.UUID | None = None,
) -> list[Contrato]:
    query = select(Contrato)
    if apenas_ativos:
        query = query.where(Contrato.ativo.is_(True))
    if tipo:
        query = query.where(Contrato.tipo == tipo)
    if titular_id:
        query = query.where(Contrato.titular_id == titular_id)
    if ativo_id:
        query = query.where(Contrato.ativo_id == ativo_id)

    query = query.order_by(Contrato.data_fim.asc().nulls_last(), Contrato.nome.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def listar_por_ativo(
    session: AsyncSession, ativo_id: uuid.UUID, apenas_ativos: bool = True
) -> list[Contrato]:
    return await listar_todos(session, ativo_id=ativo_id, apenas_ativos=apenas_ativos)


async def listar_proximos_vencimentos(
    session: AsyncSession,
    *,
    referencia: date | None = None,
    dias_antecedencia: int = 60,
) -> list[dict]:
    """Lista contratos ativos cuja data limite de decisão (data_fim - dias_aviso_previo)
    ou data de término expira nos próximos `dias_antecedencia` dias."""
    hoje = referencia or date.today()
    limite = hoje + timedelta(days=dias_antecedencia)

    query = (
        select(Contrato)
        .where(
            Contrato.ativo.is_(True),
            Contrato.data_fim.is_not(None),
            Contrato.data_fim <= limite,
        )
        .order_by(Contrato.data_fim.asc())
    )
    result = await session.execute(query)
    contratos = result.scalars().all()

    items = []
    for c in contratos:
        assert c.data_fim is not None
        dias_restantes = (c.data_fim - hoje).days
        data_limite_decisao = c.data_fim - timedelta(days=c.dias_aviso_previo)
        dias_para_decisao = (data_limite_decisao - hoje).days

        items.append(
            {
                "contrato": c,
                "dias_restantes": dias_restantes,
                "data_limite_decisao": data_limite_decisao,
                "dias_para_decisao": dias_para_decisao,
                "urgente": dias_para_decisao <= 7 or dias_restantes <= 7,
                "expirado": dias_restantes < 0,
            }
        )
    return items


async def calcular_encargo_anual_total(session: AsyncSession) -> Decimal:
    """Calcula o somatório do encargo anual de todos os contratos/seguros ativos (excluindo garantias)."""
    contratos = await listar_todos(session, apenas_ativos=True)
    total = Decimal("0")
    for c in contratos:
        if c.tipo != "garantia" and c.valor:
            total += calcular_valor_anualizado(c.valor, c.periodicidade)
    return total


async def desativar_contrato(session: AsyncSession, contrato_id: uuid.UUID) -> bool:
    contrato = await session.get(Contrato, contrato_id)
    if contrato is None:
        return False
    contrato.ativo = False
    await session.commit()
    return True
