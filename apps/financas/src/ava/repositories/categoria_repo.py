import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria


async def criar_grupo(session: AsyncSession, *, nome: str, ordem: int = 0) -> GrupoCategoria:
    grupo = GrupoCategoria(nome=nome, ordem=ordem)
    session.add(grupo)
    await session.flush()
    return grupo


async def criar_categoria(
    session: AsyncSession,
    *,
    grupo_id: uuid.UUID,
    nome: str,
    tipo: str,
    natureza: str,
    unidade_contador: str | None = None,
) -> Categoria:
    categoria = Categoria(
        grupo_id=grupo_id,
        nome=nome,
        tipo=tipo,
        natureza=natureza,
        unidade_contador=unidade_contador,
    )
    session.add(categoria)
    await session.flush()
    return categoria


async def obter_por_id(session: AsyncSession, categoria_id: uuid.UUID) -> Categoria | None:
    return await session.get(Categoria, categoria_id)


async def definir_natureza(
    session: AsyncSession, categoria_id: uuid.UUID, *, natureza: str
) -> Categoria | None:
    """Grava a natureza de uma categoria. Devolve None se a categoria não existir.

    Não valida a natureza contra o tipo — isso é da rota, que sabe devolver 422. Aqui só se grava.
    """
    categoria = await session.get(Categoria, categoria_id)
    if categoria is None:
        return None
    categoria.natureza = natureza
    await session.flush()
    return categoria


async def obter_por_nomes(session: AsyncSession, *, grupo: str, nome: str) -> Categoria | None:
    result = await session.execute(
        select(Categoria)
        .join(GrupoCategoria, GrupoCategoria.id == Categoria.grupo_id)
        .where(GrupoCategoria.nome == grupo, Categoria.nome == nome)
    )
    return result.scalar_one_or_none()


async def listar_todos_os_grupos_com_categorias(
    session: AsyncSession,
) -> list[tuple[GrupoCategoria, list[Categoria]]]:
    """Todos os grupos ativos por ordem, cada um com as suas categorias ativas (de qualquer
    tipo). Ao contrário de listar_grupos_com_categorias (que usa INNER JOIN e por isso omite
    grupos ainda sem categoria nenhuma), inclui grupos vazios — necessário na página de
    configurações, onde um grupo recém-criado tem de aparecer para se lhe poderem adicionar
    categorias."""
    grupos_result = await session.execute(
        select(GrupoCategoria)
        .where(GrupoCategoria.ativo.is_(True))
        .order_by(GrupoCategoria.ordem, GrupoCategoria.nome)
    )
    grupos = list(grupos_result.scalars().all())

    categorias_result = await session.execute(
        select(Categoria).where(Categoria.ativo.is_(True)).order_by(Categoria.nome)
    )
    categorias_por_grupo: dict[uuid.UUID, list[Categoria]] = {}
    for categoria in categorias_result.scalars().all():
        categorias_por_grupo.setdefault(categoria.grupo_id, []).append(categoria)

    return [(grupo, categorias_por_grupo.get(grupo.id, [])) for grupo in grupos]


async def listar_grupos_com_categorias(
    session: AsyncSession, *, tipo: str | None = None
) -> list[tuple[GrupoCategoria, list[Categoria]]]:
    """Grupos ativos por ordem, cada um com as suas categorias ativas por nome.

    Grupos sem nenhuma categoria que sirva o `tipo` pedido são omitidos — não faz sentido
    mostrar "Rendimentos" numa lista de categorias de despesa.
    """
    condicoes = [Categoria.ativo.is_(True)]
    if tipo is not None:
        condicoes.append(Categoria.tipo == tipo)

    result = await session.execute(
        select(GrupoCategoria, Categoria)
        .join(Categoria, Categoria.grupo_id == GrupoCategoria.id)
        .where(GrupoCategoria.ativo.is_(True), *condicoes)
        .order_by(GrupoCategoria.ordem, Categoria.nome)
    )

    agrupado: dict[uuid.UUID, tuple[GrupoCategoria, list[Categoria]]] = {}
    for grupo, categoria in result.all():
        if grupo.id not in agrupado:
            agrupado[grupo.id] = (grupo, [])
        agrupado[grupo.id][1].append(categoria)

    return list(agrupado.values())
