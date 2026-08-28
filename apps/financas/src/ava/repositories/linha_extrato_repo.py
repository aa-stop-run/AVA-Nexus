import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.linha_extrato import LinhaExtrato
from ava.repositories import movimento_repo


async def criar_linha(
    session: AsyncSession,
    *,
    conta_id: uuid.UUID,
    documento_id: uuid.UUID,
    data: date,
    valor: Decimal,
    descricao: str = "",
) -> LinhaExtrato:
    movimento = LinhaExtrato(
        conta_id=conta_id, documento_id=documento_id, data=data, valor=valor, descricao=descricao
    )
    session.add(movimento)
    await session.flush()
    return movimento


async def obter_por_id(session: AsyncSession, movimento_id: uuid.UUID) -> LinhaExtrato | None:
    return await session.get(LinhaExtrato, movimento_id)


async def contar_existentes_por_chave(
    session: AsyncSession, *, conta_id: uuid.UUID, de: date, ate: date
) -> dict[tuple[date, Decimal], int]:
    """Quantas linhas de extrato já existem para esta conta, por `(data, valor)`, no intervalo.

    Substitui `existe_para_documento_e_conta`, que era indexada ao `documento_id` e por isso não
    conseguia ver o MESMO extrato a chegar dentro de OUTRO documento — foi essa a brecha que a
    13 de Agosto de 2026 duplicou 135 movimentos, quando o extrato do BPI entrou uma vez pela
    pasta sincronizada e outra por mail. A guarda antiga existia para um problema real e
    diferente (reaprovação manual de um documento multi-secção); esta cobre os dois, porque as
    linhas que o próprio documento criou também já cá estão quando ele volta a ser processado.

    Conta por MULTIPLICIDADE e não por existência. Dois levantamentos de 10,00 € no mesmo dia são
    dois movimentos, não um — existem quatro grupos assim na base de produção só em Julho de
    2026. Uma guarda por existência apagava o segundo, e faltar dinheiro no razão é pior de
    detetar do que sobrar.

    A chave não inclui a descrição: duas passagens de OCR sobre o mesmo PDF podem escrever o
    texto de forma ligeiramente diferente, e uma guarda que dependesse disso falhava exatamente
    no caso para que existe. É o mesmo raciocínio de `casar_linha`, que nunca casa por descrição
    entre fontes diferentes.

    O valor entra na chave COM SINAL (a convenção de `linha_extrato`: positivo é entrada,
    negativo é saída), ao contrário de `importacao_ficheiro._contar_existentes_por_chave`, que
    usa `abs()` porque `movimento.valor` é sempre positivo.
    """
    resultado = await session.execute(
        select(LinhaExtrato.data, LinhaExtrato.valor).where(
            LinhaExtrato.conta_id == conta_id,
            LinhaExtrato.data >= de,
            LinhaExtrato.data <= ate,
        )
    )
    contagem: dict[tuple[date, Decimal], int] = {}
    for data_existente, valor_existente in resultado.all():
        chave = (data_existente, valor_existente)
        contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


async def listar_pendentes(session: AsyncSession) -> list[LinhaExtrato]:
    result = await session.execute(
        select(LinhaExtrato).where(LinhaExtrato.estado == "pendente").order_by(LinhaExtrato.data)
    )
    return list(result.scalars().all())


async def listar_em_revisao_manual(
    session: AsyncSession,
    *,
    busca: str | None = None,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> list[LinhaExtrato]:
    """Linhas por resolver em /movimentos. Todos os filtros são opcionais e combinam-se em AND
    — usados para o utilizador encontrar uma linha específica num histórico grande sem ter de
    percorrer tudo. `valor_min`/`valor_max` comparam o valor absoluto (o sinal indica só
    despesa/rendimento, não a grandeza que o utilizador procura)."""
    condicoes = [LinhaExtrato.estado == "revisao_manual"]
    if busca:
        condicoes.append(LinhaExtrato.descricao.ilike(f"%{busca}%"))
    if valor_min is not None:
        condicoes.append(func.abs(LinhaExtrato.valor) >= valor_min)
    if valor_max is not None:
        condicoes.append(func.abs(LinhaExtrato.valor) <= valor_max)
    if data_inicio is not None:
        condicoes.append(LinhaExtrato.data >= data_inicio)
    if data_fim is not None:
        condicoes.append(LinhaExtrato.data <= data_fim)

    result = await session.execute(
        select(LinhaExtrato).where(*condicoes).order_by(LinhaExtrato.data)
    )
    return list(result.scalars().all())


async def marcar_conciliada(
    session: AsyncSession, linha_id: uuid.UUID, movimento_id: uuid.UUID
) -> None:
    """Marca a linha como conciliada. A ligação em si vive em movimento.linha_extrato_id —
    uma só direção, o que torna estruturalmente impossível o estado antigo em que
    transacao_id e rendimento_id podiam estar ambos preenchidos."""
    linha = await session.get(LinhaExtrato, linha_id)
    assert linha is not None
    linha.estado = "conciliado"
    await movimento_repo.ligar_a_linha_extrato(session, movimento_id, linha_id)


async def marcar_conciliada_sem_ligar(session: AsyncSession, linha_id: uuid.UUID) -> None:
    """Marca a linha como conciliada sem tocar em movimento.linha_extrato_id. Usada quando a
    ligação ao Movimento já foi definida na criação (ver reconciliacao — transferências entre
    conta à ordem e conta de dívida, onde DUAS linhas — origem e destino — apontam para o MESMO
    movimento através de duas colunas distintas: linha_extrato_id e linha_extrato_destino_id.
    marcar_conciliada normal sobrescreveria a ligação de uma das duas se chamada duas vezes)."""
    linha = await session.get(LinhaExtrato, linha_id)
    assert linha is not None
    linha.estado = "conciliado"


async def marcar_revisao_manual(session: AsyncSession, movimento_id: uuid.UUID) -> None:
    movimento = await session.get(LinhaExtrato, movimento_id)
    assert movimento is not None
    movimento.estado = "revisao_manual"


async def marcar_ignorado(session: AsyncSession, movimento_id: uuid.UUID) -> None:
    movimento = await session.get(LinhaExtrato, movimento_id)
    assert movimento is not None
    movimento.estado = "ignorado"
