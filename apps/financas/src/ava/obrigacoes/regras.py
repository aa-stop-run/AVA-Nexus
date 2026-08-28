import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ava.repositories import obrigacao_repo


def _somar_anos(data_base: date, anos: int) -> date:
    try:
        return data_base.replace(year=data_base.year + anos)
    except ValueError:
        # 29 de fevereiro em ano não bissexto
        return data_base.replace(month=2, day=28, year=data_base.year + anos)


def calcular_proxima_inspecao(matricula: date, *, referencia: date) -> date:
    idade = 4
    candidata = _somar_anos(matricula, idade)
    while candidata < referencia:
        idade += 2 if idade < 8 else 1
        candidata = _somar_anos(matricula, idade)
    return candidata


def calcular_proxima_data_iuc(matricula: date, *, referencia: date) -> date:
    candidata = _somar_anos(matricula, referencia.year - matricula.year)
    if candidata < referencia:
        candidata = _somar_anos(candidata, 1)
    return candidata


def calcular_datas_imi(ano: int, *, valor_total: Decimal) -> list[date]:
    if valor_total <= Decimal("100"):
        return [date(ano, 5, 31)]
    if valor_total <= Decimal("500"):
        return [date(ano, 5, 31), date(ano, 11, 30)]
    return [date(ano, 5, 31), date(ano, 8, 31), date(ano, 11, 30)]


async def sincronizar_obrigacoes_ativo(
    session: AsyncSession,
    *,
    titular_id: uuid.UUID,
    matricula: date,
    referencia: date,
    ativo_id: uuid.UUID,
    ativo_nome: str,
) -> None:
    proxima_inspecao = calcular_proxima_inspecao(matricula, referencia=referencia)
    if not await obrigacao_repo.existe_obrigacao(
        session,
        tipo="inspecao",
        data_limite=proxima_inspecao,
        titular_id=titular_id,
        ativo_id=ativo_id,
    ):
        await obrigacao_repo.criar_obrigacao(
            session,
            tipo="inspecao",
            descricao=f"Inspeção periódica obrigatória — {ativo_nome}",
            data_limite=proxima_inspecao,
            origem="regra",
            titular_id=titular_id,
            ativo_id=ativo_id,
        )

    proxima_iuc = calcular_proxima_data_iuc(matricula, referencia=referencia)
    if not await obrigacao_repo.existe_obrigacao(
        session,
        tipo="iuc",
        data_limite=proxima_iuc,
        titular_id=titular_id,
        ativo_id=ativo_id,
    ):
        await obrigacao_repo.criar_obrigacao(
            session,
            tipo="iuc",
            descricao=f"Pagamento do IUC — {ativo_nome}",
            data_limite=proxima_iuc,
            origem="regra",
            titular_id=titular_id,
            ativo_id=ativo_id,
        )

    await session.commit()
