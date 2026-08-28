import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas import valorizacao
from ava.models.ativo import Ativo
from ava.repositories import ativo_valor_repo

# Tipos de Ativo que são veículos, e portanto os únicos que geram obrigações de inspeção e IUC
# (ver ava.alerts.scheduler.sincronizar_obrigacoes_dos_ativos_ativos). "veiculo" é o valor legado
# escrito pela migração e1a2b3c4d5e6 nas linhas que já existiam quando a tabela ainda se chamava
# `veiculo`; "carro"/"mota" são os valores que o formulário (ativo_novo.html) escreve hoje.
TIPOS_VEICULO = ("carro", "mota", "veiculo")


async def criar_ativo(
    session: AsyncSession,
    *,
    titular_id: uuid.UUID,
    nome: str,
    tipo: str,
    data_aquisicao: date | None = None,
    taxa_anual: Decimal | None = None,
    ativo_status: bool = True,
) -> Ativo:
    novo_ativo = Ativo(
        titular_id=titular_id,
        nome=nome,
        tipo=tipo,
        data_aquisicao=data_aquisicao,
        taxa_anual=taxa_anual,
        ativo=ativo_status,
    )
    session.add(novo_ativo)
    await session.flush()
    return novo_ativo


async def listar_todos_ativos(session: AsyncSession) -> list[Ativo]:
    result = await session.execute(select(Ativo).where(Ativo.ativo.is_(True)))
    return list(result.scalars().all())


async def obter_por_id(session: AsyncSession, ativo_id: uuid.UUID) -> Ativo | None:
    result = await session.execute(select(Ativo).where(Ativo.id == ativo_id))
    return result.scalars().first()


async def obter_por_nome_aproximado(session: AsyncSession, nome: str) -> Ativo | None:
    # ILIKE is PostgreSQL specific; works for SQLite with normal LIKE if collation is set, but ILIKE is generally safe for our Postgres backend.
    result = await session.execute(
        select(Ativo).where(Ativo.ativo.is_(True), Ativo.nome.ilike(f"%{nome}%"))
    )
    return result.scalars().first()


async def valor_em_data(
    session: AsyncSession, ativo: Ativo, data_ref: date
) -> valorizacao.ValorAtivo | None:
    """Valor do ativo em `data_ref`, projetado a partir da observação mais recente até essa data.

    Devolve None quando não há nenhuma observação até `data_ref` — inclusive para um bem que
    ainda nunca foi avaliado. None significa "não sei quanto vale", que é diferente de zero:
    somar zero ao património afirmaria que o bem não vale nada.
    """
    observacao = await ativo_valor_repo.obter_valor_em_data(session, ativo.id, data_ref)
    if observacao is None:
        return None

    if observacao.data == data_ref:
        return valorizacao.ValorAtivo(observacao.valor, False, observacao.data)

    taxa = valorizacao.taxa_de(ativo.tipo, ativo.taxa_anual)
    projetado = valorizacao.projetar(observacao.valor, observacao.data, data_ref, taxa)
    return valorizacao.ValorAtivo(projetado, True, observacao.data)


async def valor_atual(session: AsyncSession, ativo: Ativo) -> valorizacao.ValorAtivo | None:
    """Atalho para valor_em_data(hoje) — o caso de longe mais usado."""
    return await valor_em_data(session, ativo, date.today())
