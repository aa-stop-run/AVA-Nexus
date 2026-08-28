import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.saldos import TIPOS_PASSIVO
from ava.models.conta import Conta


async def criar_conta(
    session: AsyncSession,
    *,
    titular_id: uuid.UUID,
    instituicao: str,
    tipo: str,
    nome: str,
    categoria_divida: str | None = None,
    categoria_investimento: str | None = None,
    ativo_id: uuid.UUID | None = None,
) -> Conta:
    conta = Conta(
        titular_id=titular_id,
        instituicao=instituicao,
        tipo=tipo,
        nome=nome,
        categoria_divida=categoria_divida,
        categoria_investimento=categoria_investimento,
        ativo_id=ativo_id,
    )
    session.add(conta)
    await session.flush()
    return conta


async def atualizar_conta(
    session: AsyncSession,
    *,
    conta_id: uuid.UUID,
    titular_id: uuid.UUID,
    instituicao: str,
    tipo: str,
    nome: str,
    categoria_divida: str | None = None,
    categoria_investimento: str | None = None,
) -> Conta | None:
    conta = await obter_por_id(session, conta_id)
    if conta is None:
        return None
    conta.titular_id = titular_id
    conta.instituicao = instituicao
    conta.tipo = tipo
    conta.nome = nome
    conta.categoria_divida = categoria_divida
    conta.categoria_investimento = categoria_investimento
    await session.flush()
    return conta


async def desativar_conta(session: AsyncSession, conta_id: uuid.UUID) -> bool:
    conta = await obter_por_id(session, conta_id)
    if conta is None:
        return False
    conta.ativo = False
    await session.flush()
    return True


async def obter_por_id(session: AsyncSession, conta_id: uuid.UUID) -> Conta | None:
    return await session.get(Conta, conta_id)


async def listar_todas(session: AsyncSession) -> list[Conta]:
    result = await session.execute(select(Conta).where(Conta.ativo.is_(True)).order_by(Conta.nome))
    return list(result.scalars().all())


async def listar_por_titular(session: AsyncSession, titular_id: uuid.UUID) -> list[Conta]:
    result = await session.execute(
        select(Conta).where(Conta.titular_id == titular_id, Conta.ativo.is_(True)).order_by(Conta.nome)
    )
    return list(result.scalars().all())


async def obter_ou_criar_por_instituicao(
    session: AsyncSession, *, titular_id: uuid.UUID, instituicao: str, tipo: str, nome: str | None = None
) -> Conta:
    tipos_validos = [tipo]
    if tipo in TIPOS_PASSIVO:
        tipos_validos = list(TIPOS_PASSIVO)

    result = await session.execute(
        select(Conta).where(
            Conta.titular_id == titular_id, 
            Conta.instituicao == instituicao, 
            Conta.tipo.in_(tipos_validos)
        )
    )
    contas = list(result.scalars().all())
    
    if nome is not None:
        for conta in contas:
            if conta.nome == nome:
                return conta
        return await criar_conta(session, titular_id=titular_id, instituicao=instituicao, tipo=tipo, nome=nome)
    
    if len(contas) == 1:
        return contas[0]
    if len(contas) > 1:
        # Se for ambíguo e não tivermos nome, não podemos adivinhar
        return contas[0]
        
    return await criar_conta(session, titular_id=titular_id, instituicao=instituicao, tipo=tipo, nome=nome)


async def obter_ou_criar_por_nome(
    session: AsyncSession,
    *,
    titular_id: uuid.UUID,
    instituicao: str,
    tipo: str,
    nome: str,
    categoria_divida: str | None = None,
) -> Conta:
    # Tarefa 10 (Extracto Integrado do BPI): obter_ou_criar_por_instituicao combina por
    # (titular_id, instituicao, tipo), sem "nome" — o que funde duas contas do mesmo tipo na
    # mesma instituição (ex. "Crédito Pessoal" e "Mortgage & Loans/Hipotecário", ambos
    # tipo="divida" em instituicao="BPI") numa só Conta. Esta variante acrescenta "nome" ao
    # critério de combinação precisamente para o caminho multi-conta (um documento, várias
    # secções/produtos) não fundir contas distintas. Não substitui obter_ou_criar_por_instituicao
    # — o caminho de conta única existente continua a usar essa função tal como está.
    #
    # tipo também precisa de alargar para a família TIPOS_PASSIVO (divida/emprestimo/
    # cartao_credito), tal como obter_ou_criar_por_instituicao já fazia — incidente real
    # (2026-08-15): o parser BPI passa sempre tipo_conta="divida" (genérico), mas contas de
    # crédito já existentes podem estar classificadas com um tipo mais específico ("emprestimo").
    # Sem este alargamento, `Conta.tipo == tipo` nunca batia com a conta certa mesmo com
    # nome/instituicao/titular idênticos, e cada importação criava uma conta "fantasma" nova,
    # duplicando o saldo de dívida mostrado em /patrimonio.
    tipos_validos = [tipo]
    if tipo in TIPOS_PASSIVO:
        tipos_validos = list(TIPOS_PASSIVO)

    result = await session.execute(
        select(Conta).where(
            Conta.titular_id == titular_id,
            Conta.instituicao == instituicao,
            Conta.tipo.in_(tipos_validos),
            Conta.nome == nome,
        )
    )
    # scalars().first() em vez de scalar_one_or_none(): com o alargamento acima, é teoricamente
    # possível (embora não visto em produção) existirem duas contas da família TIPOS_PASSIVO com
    # o mesmo nome — scalar_one_or_none() rebentaria com MultipleResultsFound nesse caso, em vez
    # de desempatar como obter_ou_criar_por_instituicao já faz.
    conta = result.scalars().first()
    if conta is not None:
        return conta
    return await criar_conta(
        session,
        titular_id=titular_id,
        instituicao=instituicao,
        tipo=tipo,
        nome=nome,
        categoria_divida=categoria_divida,
    )


async def listar_todas_ativas(session: AsyncSession) -> list[Conta]:
    result = await session.execute(select(Conta).where(Conta.ativo.is_(True)))
    return list(result.scalars().all())


async def definir_ativo(
    session: AsyncSession, conta_id: uuid.UUID, ativo_id: uuid.UUID | None
) -> bool:
    """Liga (ou desliga, com None) uma conta de dívida ao bem que financiou.

    Devolve False se a conta não existir. Não valida o ativo: quem chama é que sabe se o
    escolheu de uma lista real — ver a rota em ava.api.configuracoes.
    """
    conta = await session.get(Conta, conta_id)
    if conta is None:
        return False
    conta.ativo_id = ativo_id
    await session.flush()
    return True


async def listar_dividas_do_ativo(session: AsyncSession, ativo_id: uuid.UUID) -> list[Conta]:
    """As contas de dívida ligadas a este bem. Um bem pode ter mais do que uma (spec §2).

    Filtra por `ativo` e por `tipo` de propósito, para o "Em dívida" da página do bem
    concordar exatamente com o conjunto que `/patrimonio` soma em `total_dividas`: uma conta
    apagada (`desativar_conta`) ou reclassificada (`atualizar_conta`) deixa de ser dívida lá e
    não pode continuar a ser subtraída aqui — senão o valor líquido do bem ficava a descontar
    um saldo que já não existe em lado nenhum do património.
    """
    result = await session.execute(
        select(Conta).where(
            Conta.ativo_id == ativo_id,
            Conta.ativo.is_(True),
            Conta.tipo.in_(TIPOS_PASSIVO),
        )
    )
    return list(result.scalars().all())


async def listar_dividas_ativas(session: AsyncSession) -> list[Conta]:
    """Contas de dívida ativas, para os seletores de crédito."""
    result = await session.execute(
        select(Conta)
        .where(Conta.ativo.is_(True), Conta.tipo.in_(TIPOS_PASSIVO))
        .order_by(Conta.nome)
    )
    return list(result.scalars().all())
