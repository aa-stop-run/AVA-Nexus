import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ava.models.orcamento import Orcamento

async def obter_por_id(session: AsyncSession, orcamento_id: uuid.UUID) -> Orcamento | None:
    result = await session.execute(
        select(Orcamento).where(Orcamento.id == orcamento_id)
    )
    return result.scalar_one_or_none()


async def listar_orcamentos(session: AsyncSession, ano: int, mes: int) -> Sequence[Orcamento]:
    # Obter todos os orçamentos
    result = await session.execute(select(Orcamento))
    all_budgets = result.scalars().all()
    
    from collections import defaultdict
    by_group = defaultdict(list)
    for b in all_budgets:
        by_group[b.grupo_categoria_id].append(b)
        
    final_budgets = []
    for gid, budgets in by_group.items():
        # 1. Match exato
        exact = next((b for b in budgets if b.ano == ano and b.mes == mes), None)
        if exact:
            final_budgets.append(exact)
            continue
            
        # 2. Mais recente no passado (o budget que estava ativo naquele mês)
        past_budgets = [b for b in budgets if (b.ano < ano) or (b.ano == ano and b.mes < mes)]
        if past_budgets:
            latest_past = max(past_budgets, key=lambda b: (b.ano, b.mes))
            final_budgets.append(latest_past)
            continue
            
        # 3. Mais antigo no futuro (permite que orçamentos criados agora se apliquem ao passado se não houver registo)
        future_budgets = [b for b in budgets if (b.ano > ano) or (b.ano == ano and b.mes > mes)]
        if future_budgets:
            earliest_future = min(future_budgets, key=lambda b: (b.ano, b.mes))
            final_budgets.append(earliest_future)
            
    return final_budgets

async def obter_por_grupo_e_mes(
    session: AsyncSession, grupo_categoria_id: uuid.UUID, ano: int, mes: int
) -> Orcamento | None:
    """Match EXATO de (grupo, ano, mes) — ao contrário de `listar_orcamentos`, que faz fallback
    para o orçamento vigente noutro mês.

    Existe para quem precisa de saber se este mês tem orçamento PRÓPRIO (é o caso de quem grava
    o formulário): usar `listar_orcamentos` para essa decisão faz com que gravar o orçamento de
    setembro encontre o de março como "existente" e o sobrescreva, apagando-o do histórico.
    """
    result = await session.execute(
        select(Orcamento).where(
            Orcamento.grupo_categoria_id == grupo_categoria_id,
            Orcamento.ano == ano,
            Orcamento.mes == mes,
        )
    )
    return result.scalar_one_or_none()


async def criar_orcamento(
    session: AsyncSession, grupo_categoria_id: uuid.UUID, ano: int, mes: int, limite_mensal: Decimal
) -> Orcamento:
    orcamento = Orcamento(
        grupo_categoria_id=grupo_categoria_id,
        ano=ano,
        mes=mes,
        limite_mensal=limite_mensal,
    )
    session.add(orcamento)
    await session.commit()
    await session.refresh(orcamento)
    return orcamento


async def atualizar_orcamento(
    session: AsyncSession, orcamento_id: uuid.UUID, limite_mensal: Decimal
) -> Orcamento | None:
    orcamento = await obter_por_id(session, orcamento_id)
    if not orcamento:
        return None
    
    orcamento.limite_mensal = limite_mensal
    await session.commit()
    await session.refresh(orcamento)
    return orcamento
