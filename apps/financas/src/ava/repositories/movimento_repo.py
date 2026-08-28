import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, extract, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.categorizacao_automatica import padrao_de_descricao
from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria
from ava.models.linha_extrato import LinhaExtrato
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.repositories import ressarcimento_repo


class SomaDasLinhasNaoBate(Exception):
    """A soma das linhas não iguala o total do movimento, ou não há linha nenhuma."""


class ValorNaoPositivo(Exception):
    """movimento.valor não é positivo (regra global: valor é sempre positivo, a direção vem de
    tipo — ver Achado Importante, revisão final Fase A). Exceção própria em vez de reaproveitar
    SomaDasLinhasNaoBate: são invariantes distintos (uma soma incorreta vs. um sinal errado) e
    misturá-los num só nome faria os chamadores perderem a informação de qual regra falhou."""


@dataclass(frozen=True)
class MovimentoDeCategoria:
    """Uma despesa desta categoria, para a lista que se abre ao clicar numa categoria no
    dashboard (`GET /categorias/{categoria_id}/movimentos`)."""

    movimento_id: uuid.UUID
    data: date
    descricao: str
    valor: Decimal


@dataclass(frozen=True)
class LinhaNova:
    """Linha a criar. Frozen: descreve uma intenção, não um registo mutável."""

    valor: Decimal
    categoria_id: uuid.UUID | None = None
    descricao: str = ""
    quantidade: Decimal | None = None
    unidade: str | None = None
    ativo_id: uuid.UUID | None = None
    conta_relacionada_id: uuid.UUID | None = None
    leitura_odometro: int | None = None
    ressarcimento_id: uuid.UUID | None = None


async def criar_movimento(
    session: AsyncSession,
    *,
    tipo: str,
    valor: Decimal,
    data: date,
    linhas: list[LinhaNova],
    origem: str,
    conta_id: uuid.UUID | None = None,
    conta_destino_id: uuid.UUID | None = None,
    titular_id: uuid.UUID | None = None,
    registado_por: uuid.UUID | None = None,
    ambito: str = "comum",
    descricao: str = "",
    documento_id: uuid.UUID | None = None,
    fornecedor_id: uuid.UUID | None = None,
    recorrente_id: uuid.UUID | None = None,
    linha_extrato_id: uuid.UUID | None = None,
    linha_extrato_destino_id: uuid.UUID | None = None,
) -> Movimento:
    """Cria um movimento com as suas linhas, impondo Σ(linhas) == valor e valor > 0.

    A validação acontece antes de qualquer escrita: um movimento nunca chega à base de dados
    com as linhas desequilibradas nem com um valor não positivo.
    """
    if not linhas:
        raise SomaDasLinhasNaoBate("um movimento tem de ter pelo menos uma linha")

    soma = sum((linha.valor for linha in linhas), Decimal("0"))
    if soma != valor:
        raise SomaDasLinhasNaoBate(f"soma das linhas {soma} != total do movimento {valor}")

    # Regra global do projeto: movimento.valor é sempre positivo; a direção vem de `tipo`
    # ("entrada"/"saida"/"transferencia"), nunca do sinal de valor. Só o TOTAL do movimento é
    # verificado aqui — uma LinhaNova individual pode legitimamente ter valor negativo numa
    # divisão (ex. um estorno parcial que reduz outra linha da mesma divisão), desde que a soma
    # continue a fechar em valor > 0 (já garantido pelo checksum acima).
    if valor <= 0:
        raise ValorNaoPositivo(f"movimento.valor tem de ser positivo, recebido {valor}")

    movimento = Movimento(
        tipo=tipo,
        valor=valor,
        data=data,
        origem=origem,
        conta_id=conta_id,
        conta_destino_id=conta_destino_id,
        titular_id=titular_id,
        registado_por=registado_por,
        ambito=ambito,
        descricao=descricao,
        documento_id=documento_id,
        fornecedor_id=fornecedor_id,
        recorrente_id=recorrente_id,
        linha_extrato_id=linha_extrato_id,
        linha_extrato_destino_id=linha_extrato_destino_id,
        linhas=[
            MovimentoLinha(
                categoria_id=linha.categoria_id,
                valor=linha.valor,
                descricao=linha.descricao,
                quantidade=linha.quantidade,
                unidade=linha.unidade,
                ativo_id=linha.ativo_id,
                conta_relacionada_id=linha.conta_relacionada_id,
                leitura_odometro=linha.leitura_odometro,
                ressarcimento_id=linha.ressarcimento_id,
            )
            for linha in linhas
        ],
    )
    session.add(movimento)
    await session.flush()
    return movimento


async def obter_por_id(session: AsyncSession, movimento_id: uuid.UUID) -> Movimento | None:
    return await session.get(Movimento, movimento_id)


async def apagar(session: AsyncSession, movimento: Movimento) -> None:
    """Apaga o movimento e as suas linhas (cascade a nível de BD — ver migração
    aa0f40c6833b, movimento_linha_movimento_id_fkey ondelete='CASCADE'). Usada por
    ava.ingestion.reconciliacao.desfazer_movimento para desfazer uma categorização errada."""
    await session.delete(movimento)


async def listar_por_periodo(
    session: AsyncSession, *, inicio: date, fim: date, tipo: str | None = None
) -> list[Movimento]:
    condicoes = [Movimento.data >= inicio, Movimento.data <= fim]
    if tipo is not None:
        condicoes.append(Movimento.tipo == tipo)

    result = await session.execute(
        select(Movimento).where(*condicoes).order_by(Movimento.data.desc(), Movimento.criado_em.desc())
    )
    return list(result.scalars().all())


async def listar_por_conta(
    session: AsyncSession,
    conta_id: uuid.UUID,
    *,
    busca: str | None = None,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    tipo_movimento: str | None = None,
) -> list[Movimento]:
    # Uma transferência (ex. amortização de crédito) tem esta conta do lado de conta_id (origem)
    # OU de conta_destino_id (destino) — sem o `or_`, o movimento só apareceria no histórico de
    # uma das duas contas envolvidas, escondendo metade da transferência.
    #
    # Filtros opcionais (combinam-se em AND): usados para o utilizador encontrar um movimento
    # específico num histórico grande. Movimento.valor é sempre positivo (ver A-P3/A-P6 — o
    # sinal vive em `tipo`, não em `valor`), por isso valor_min/max comparam diretamente, sem
    # abs() (ao contrário de linha_extrato_repo.listar_em_revisao_manual).
    condicoes = [or_(Movimento.conta_id == conta_id, Movimento.conta_destino_id == conta_id)]
    if busca:
        condicoes.append(Movimento.descricao.ilike(f"%{busca}%"))
    if valor_min is not None:
        condicoes.append(Movimento.valor >= valor_min)
    if valor_max is not None:
        condicoes.append(Movimento.valor <= valor_max)
    if data_inicio is not None:
        condicoes.append(Movimento.data >= data_inicio)
    if data_fim is not None:
        condicoes.append(Movimento.data <= data_fim)
    if tipo_movimento == "despesa":
        condicoes.append(Movimento.tipo == "saida")
    elif tipo_movimento == "rendimento":
        condicoes.append(Movimento.tipo == "entrada")

    result = await session.execute(
        select(Movimento)
        .options(selectinload(Movimento.linhas).selectinload(MovimentoLinha.categoria))
        .where(*condicoes)
        .order_by(Movimento.data.desc(), Movimento.criado_em.desc())
    )
    return list(result.scalars().all())


async def listar_transferencias_sem_categoria(
    session: AsyncSession,
    *,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> list[Movimento]:
    """Transferências (ver ava.ingestion.reconciliacao.conciliar_amortizacoes_de_credito) cuja
    linha ainda não tem categoria — mostradas em /movimentos para o utilizador escolher.

    Sem filtro de `busca`: a descrição é sempre o literal "Amortização de capital" (ver
    conciliar_amortizacoes_de_credito), filtrar por texto não distinguiria nada aqui.
    """
    from ava.models.conta import Conta
    from sqlalchemy.orm import aliased
    
    ContaOrigem = aliased(Conta)
    ContaDestino = aliased(Conta)
    
    condicoes = [
        Movimento.tipo == "transferencia", 
        MovimentoLinha.categoria_id.is_(None)
    ]
    if valor_min is not None:
        condicoes.append(Movimento.valor >= valor_min)
    if valor_max is not None:
        condicoes.append(Movimento.valor <= valor_max)
    if data_inicio is not None:
        condicoes.append(Movimento.data >= data_inicio)
    if data_fim is not None:
        condicoes.append(Movimento.data <= data_fim)

    result = await session.execute(
        select(Movimento)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .outerjoin(ContaOrigem, Movimento.conta_id == ContaOrigem.id)
        .outerjoin(ContaDestino, Movimento.conta_destino_id == ContaDestino.id)
        .where(*condicoes)
        .where(
            or_(
                ContaDestino.id.is_(None),
                ~((ContaOrigem.tipo.in_(["a_ordem", "poupanca"])) & (ContaDestino.tipo.in_(["a_ordem", "poupanca"])))
            )
        )
        .order_by(Movimento.data.desc())
    )
    return list(result.scalars().unique().all())


async def existe_do_recorrente_no_mes(
    session: AsyncSession, *, recorrente_id: uuid.UUID, ano: int, mes: int
) -> bool:
    """Idempotência da geração de recorrentes: por (recorrente, ano-mês), não por data exata.

    Se o utilizador mudar dia_do_mes a meio do mês, isto evita gerar um segundo movimento
    para o mesmo mês.
    """
    result = await session.execute(
        select(Movimento.id).where(
            Movimento.recorrente_id == recorrente_id,
            extract("year", Movimento.data) == ano,
            extract("month", Movimento.data) == mes,
        )
    )
    return result.first() is not None


async def listar_candidatos_para_conciliar(
    session: AsyncSession, *, tipo: str, valor: Decimal, data: date, janela_dias: int
) -> list[Movimento]:
    """Movimentos do tipo dado, valor exato, dentro da janela, ainda não ligados a extrato."""
    result = await session.execute(
        select(Movimento).where(
            Movimento.tipo == tipo,
            Movimento.valor == valor,
            Movimento.data >= data - timedelta(days=janela_dias),
            Movimento.data <= data + timedelta(days=janela_dias),
            Movimento.linha_extrato_id.is_(None),
        )
    )
    return list(result.scalars().all())


async def listar_sem_linha_extrato(
    session: AsyncSession, *, tipo: str, limite_data: date, origem: str
) -> list[Movimento]:
    """Movimentos de uma origem que passaram do prazo sem nunca terem reconciliado com um extrato.

    É o alerta inverso: "esta fatura nunca foi debitada".
    """
    result = await session.execute(
        select(Movimento).where(
            Movimento.tipo == tipo,
            Movimento.origem == origem,
            Movimento.data <= limite_data,
            Movimento.linha_extrato_id.is_(None),
        )
    )
    return list(result.scalars().all())


async def historico_valores_fornecedor(
    session: AsyncSession, fornecedor_id: uuid.UUID, limite: int = 12
) -> list[Decimal]:
    """Valores recentes de saída deste fornecedor, para o teto de magnitude das faturas (A-P3)."""
    result = await session.execute(
        select(Movimento.valor)
        .where(Movimento.fornecedor_id == fornecedor_id, Movimento.tipo == "saida")
        .order_by(Movimento.data.desc())
        .limit(limite)
    )
    return list(result.scalars().all())


async def historico_pagamentos_fornecedor(
    session: AsyncSession, fornecedor_id: uuid.UUID, limite: int = 12
) -> list[tuple[date, Decimal]]:
    """(data, valor) dos pagamentos mais recentes a este fornecedor, mais recente primeiro --
    para "Explorar por fornecedor" em /insights (spec 2026-08-20-insights-financeiros-design §5).

    Não reaproveita `historico_valores_fornecedor`: essa devolve só valores (suficiente para o
    teto de magnitude das faturas, que nunca mostra nada ao utilizador), sem data — insuficiente
    para uma tabela onde "quando" é metade da pergunta. Duas funções distintas em vez de mudar a
    existente e arriscar o único chamador dela (faturas.py).
    """
    result = await session.execute(
        select(Movimento.data, Movimento.valor)
        .where(Movimento.fornecedor_id == fornecedor_id, Movimento.tipo == "saida")
        .order_by(Movimento.data.desc())
        .limit(limite)
    )
    return [(data, valor) for data, valor in result.all()]


async def historico_valores_categoria(
    session: AsyncSession, categoria_id: uuid.UUID, limite: int = 12
) -> list[Decimal]:
    """Valores recentes de linhas desta categoria, mais recente primeiro -- para a deteção de
    outlier ao categorizar um movimento (spec 2026-08-20-insights-financeiros-design §7.1).

    Por `movimento_linha.valor`, não `movimento.valor`: uma categoria é uma propriedade da linha,
    não do movimento inteiro (o mesmo motivo de `margem_repo.margem_estrutural` e
    `movimento_repo.totais_por_categoria` iterarem linhas, não movimentos).
    """
    result = await session.execute(
        select(MovimentoLinha.valor)
        .join(Movimento, Movimento.id == MovimentoLinha.movimento_id)
        .where(MovimentoLinha.categoria_id == categoria_id)
        .order_by(Movimento.data.desc())
        .limit(limite)
    )
    return list(result.scalars().all())


async def listar_por_categoria(
    session: AsyncSession, *, categoria_id: uuid.UUID, inicio: date, fim: date,
    titular_id: uuid.UUID | None = None,
) -> list[MovimentoDeCategoria]:
    """As despesas desta categoria no período, mais recente primeiro -- para a lista que se abre
    ao clicar numa categoria em "Despesas por categoria" no dashboard.

    Mesmo filtro de tipo que `totais_por_categoria` usa para despesas (`saida`, `transferencia`),
    para a lista bater certo com o total já mostrado -- um total que inclui amortizações sem uma
    lista que também as inclua deixava o utilizador sem explicação para a diferença.

    `movimento.descricao`, não `linha.descricao`: mesma convenção de `listar_por_conta` /
    `conta_movimentos.html` -- é o texto que o utilizador já reconhece do extrato. `valor` vem da
    LINHA, não do movimento: um movimento dividido por várias categorias mostra aqui só a fatia
    desta categoria, não o total do movimento inteiro (mesmo motivo de `historico_valores_categoria`).
    """
    condicoes = [
        MovimentoLinha.categoria_id == categoria_id,
        Movimento.tipo.in_(("saida", "transferencia")),
        Movimento.data >= inicio,
        Movimento.data <= fim,
    ]
    if titular_id is not None:
        condicoes.append(Movimento.titular_id == titular_id)

    result = await session.execute(
        select(Movimento.id, Movimento.data, Movimento.descricao, MovimentoLinha.valor)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .where(*condicoes)
        .order_by(Movimento.data.desc(), Movimento.criado_em.desc())
    )
    return [
        MovimentoDeCategoria(movimento_id=mid, data=data, descricao=descricao, valor=valor)
        for mid, data, descricao, valor in result.all()
    ]


# Origens que significam "o utilizador registou isto à mão". "manual" é a atual (/registo e
# /registo-rapido); as outras são históricas e preservadas para retrocompatibilidade.
ORIGENS_REGISTO_MANUAL = ("manual", "web", "telegram")

# Origens cujos movimentos o utilizador pode categorizar à mão. Inclui as de registo manual e
# `ficheiro`: um movimento importado do banco sem padrão aprendido tem de ser categorizável,
# senão não conta para orçamento nenhum (totais_por_categoria faz inner join com Categoria) e não
# há forma de o corrigir — nem na lista de /movimentos, nem na rota que grava a categoria
# (revisão final da spec 2026-08-09, achado 1).
ORIGENS_CATEGORIZAVEIS = ORIGENS_REGISTO_MANUAL + ("ficheiro",)


async def historico_valores_registo_rapido(
    session: AsyncSession, *, titular_id: uuid.UUID, tipo: str, limite: int = 12
) -> list[Decimal]:
    """Valores recentes registados à mão por este titular, para o teto de magnitude (A-P3)."""
    result = await session.execute(
        select(Movimento.valor)
        .where(
            Movimento.titular_id == titular_id,
            Movimento.tipo == tipo,
            Movimento.origem.in_(ORIGENS_REGISTO_MANUAL),
        )
        .order_by(Movimento.data.desc())
        .limit(limite)
    )
    return list(result.scalars().all())


async def totais_por_categoria(
    session: AsyncSession, *, inicio: date, fim: date, tipo: str | tuple[str, ...], titular_id: uuid.UUID | None = None
) -> list[tuple[GrupoCategoria, Categoria, Decimal]]:
    """Agrupa movimentos por categoria num período, somando os valores.

    Retorna lista de tuplos (GrupoCategoria, Categoria, total) ordenados por total descendente.
    Reutilizável para despesas (tipo="saida", ou ("saida","transferencia")) e rendimentos
    (tipo="entrada").

    Processa em Python, não em SQL puro (mesmo padrão de margem_repo.margem_estrutural), porque
    o desconto de ressarcimento (spec 2026-08-14 §4.2) depende de uma regra — "só quando o grupo
    tem exatamente uma despesa" — que não é uma condição de filtro, é uma decisão por linha.
    """
    if isinstance(tipo, str):
        tipo_cond = Movimento.tipo == tipo
    else:
        tipo_cond = Movimento.tipo.in_(tipo)

    query = (
        select(GrupoCategoria, Categoria, MovimentoLinha.valor, MovimentoLinha.ressarcimento_id, Movimento.tipo)
        .join(Categoria, Categoria.grupo_id == GrupoCategoria.id)
        .join(MovimentoLinha, MovimentoLinha.categoria_id == Categoria.id)
        .join(Movimento, Movimento.id == MovimentoLinha.movimento_id)
        .where(tipo_cond, Movimento.data >= inicio, Movimento.data <= fim)
    )
    if titular_id:
        query = query.where(Movimento.titular_id == titular_id)

    linhas = list(await session.execute(query))

    ids_ressarcimento = {
        ressarcimento_id for _, _, _, ressarcimento_id, _ in linhas if ressarcimento_id is not None
    }
    resumos = {
        rid: await ressarcimento_repo.resumo(session, rid) for rid in ids_ressarcimento
    }

    totais: dict[uuid.UUID, Decimal] = {}
    info_categoria: dict[uuid.UUID, tuple[GrupoCategoria, Categoria]] = {}

    for grupo, categoria, valor, ressarcimento_id, tipo_movimento in linhas:
        info_categoria[categoria.id] = (grupo, categoria)

        valor_efetivo = valor
        if ressarcimento_id is not None and tipo_movimento in ("saida", "entrada"):
            resumo_grupo = resumos[ressarcimento_id]
            grupo_simples = resumo_grupo.n_despesas == 1
            if tipo_movimento == "saida" and grupo_simples:
                valor_efetivo = resumo_grupo.liquido
            elif tipo_movimento == "entrada" and grupo_simples:
                # Já contabilizado via a despesa que desconta — não soma como rendimento.
                continue

        totais[categoria.id] = totais.get(categoria.id, Decimal("0")) + valor_efetivo

    resultado = [
        (info_categoria[cat_id][0], info_categoria[cat_id][1], total)
        for cat_id, total in totais.items()
    ]
    resultado.sort(key=lambda item: item[2], reverse=True)
    return resultado


async def ligar_a_linha_extrato(
    session: AsyncSession, movimento_id: uuid.UUID, linha_extrato_id: uuid.UUID
) -> None:
    movimento = await session.get(Movimento, movimento_id)
    assert movimento is not None
    movimento.linha_extrato_id = linha_extrato_id


async def obter_categoria_mais_recente_por_padrao(
    session: AsyncSession, *, tipo: str, padrao: str, conta_id: uuid.UUID
) -> uuid.UUID | None:
    """Categoria usada da última vez que uma linha de extrato desta MESMA conta com o mesmo
    padrão de descrição (ver ava.financas.categorizacao_automatica.padrao_de_descricao) foi
    categorizada — usada para reconhecer transações recorrentes do mesmo comerciante sem repetir
    a escolha manual do utilizador a cada mês. Normaliza em Python (não em SQL) para manter uma
    única definição de "mesmo padrão" partilhada com o resto do módulo.

    Restrito a `conta_id` (achado de revisão): algumas descrições são idênticas e sem dígito
    nenhum entre contas DIFERENTES do mesmo tipo (ex.: parse_banco_bpi devolve
    descricao="AMORTIZACAO DE CAPITAL" tanto para Crédito Pessoal como para Crédito
    Habitação/Hipotecário — ver banco_bpi.py). Sem esta restrição, categorizar a amortização de
    um crédito aplicaria a mesma categoria ao crédito completamente diferente da mesma família.

    Nota: se o movimento encontrado for "dividido" (mais que uma MovimentoLinha com categorias
    diferentes — ver MovimentoLinha), a categoria devolvida é a da primeira linha na ordem que o
    Postgres devolver, não definida explicitamente. Assunção aceite: este caminho serve o caso
    comum de uma linha de extrato com uma categoria só.
    """
    result = await session.execute(
        select(LinhaExtrato.descricao, MovimentoLinha.categoria_id)
        .join(Movimento, Movimento.linha_extrato_id == LinhaExtrato.id)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .where(
            Movimento.tipo == tipo,
            Movimento.conta_id == conta_id,
            MovimentoLinha.categoria_id.is_not(None),
        )
        .order_by(Movimento.criado_em.desc())
    )
    for descricao, categoria_id in result.all():
        if padrao_de_descricao(descricao) == padrao:
            return categoria_id
    return None


async def fluxo_entre(
    session: AsyncSession, conta_id: uuid.UUID, *, de: date | None, ate: date
) -> tuple[Decimal, Decimal]:
    """(entradas, saídas) de uma conta no intervalo `(de, ate]`. Ambas positivas.

    O intervalo é aberto à esquerda de propósito: `de` é a data de uma âncora, e a âncora já
    contém tudo o que aconteceu até esse dia inclusive. Contar outra vez o movimento do próprio
    dia da âncora somá-lo-ia duas vezes. `de=None` significa "desde sempre".

    Uma conta é tocada por dois lados (spec §4.1): `conta_id` (saídas, entradas e a perna de
    saída de uma transferência) e `conta_destino_id` (a perna de entrada). Ambos contam.

    O sinal NÃO é aplicado aqui — esta função não sabe se a conta é um ativo ou um passivo. Isso
    é `financas.saldos.derivar`.
    """
    condicoes = [
        or_(Movimento.conta_id == conta_id, Movimento.conta_destino_id == conta_id),
        Movimento.data <= ate,
    ]
    if de is not None:
        condicoes.append(Movimento.data > de)

    entra = func.coalesce(
        func.sum(Movimento.valor).filter(
            or_(
                and_(Movimento.tipo == "entrada", Movimento.conta_id == conta_id),
                and_(Movimento.tipo == "transferencia", Movimento.conta_destino_id == conta_id),
            )
        ),
        0,
    )
    sai = func.coalesce(
        func.sum(Movimento.valor).filter(
            or_(
                and_(Movimento.tipo == "saida", Movimento.conta_id == conta_id),
                and_(Movimento.tipo == "transferencia", Movimento.conta_id == conta_id),
            )
        ),
        0,
    )

    resultado = await session.execute(select(entra, sai).where(*condicoes))
    entradas, saidas = resultado.one()
    return Decimal(entradas), Decimal(saidas)
