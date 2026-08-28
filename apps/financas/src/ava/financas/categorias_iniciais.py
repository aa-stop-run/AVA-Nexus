"""Conjunto inicial de grupos e categorias, e a sementeira usada pela migração.

A função `semear_categorias` recebe uma Connection síncrona (não uma AsyncSession) para
poder ser chamada tanto de dentro de uma migração Alembic (`op.get_bind()`) como de um
teste (`await session.connection()` + `run_sync`). Usa construções Table/Column locais em
vez dos modelos ORM: uma migração é um artefacto congelado e não deve depender de
definições de modelo que evoluem depois dela.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import (Boolean, Column, Integer, MetaData, String, Table, inspect, insert,
                         select, update)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection


class CategoriaInicial(NamedTuple):
    nome: str
    tipo: str  # despesa | receita
    natureza: str  # receita: recorrente|extraordinario. despesa: fixa|variavel|poupanca
    unidade_contador: str | None = None


class GrupoInicial(NamedTuple):
    nome: str
    categorias: tuple[CategoriaInicial, ...]


_D = "despesa"
_R = "receita"
# Naturezas (spec 2026-08-13, §3.2). Abreviadas para a lista abaixo caber numa linha por
# categoria — a legibilidade da tabela é o que permite revê-la de relance.
_FIX = "fixa"
_VAR = "variavel"
_POU = "poupanca"
_REC = "recorrente"
_EXT = "extraordinario"

GRUPOS_INICIAIS: tuple[GrupoInicial, ...] = (
    GrupoInicial("Habitação", (
        CategoriaInicial("Renda", _D, _FIX),
        CategoriaInicial("Eletricidade", _D, _FIX, "kWh"),
        CategoriaInicial("Água", _D, _FIX, "m3"),
        CategoriaInicial("Gás", _D, _FIX, "m3"),
        CategoriaInicial("Condomínio", _D, _FIX),
        CategoriaInicial("Internet e TV", _D, _FIX),
        CategoriaInicial("Manutenção", _D, _VAR),
        CategoriaInicial("Seguro multirriscos", _D, _FIX),
        CategoriaInicial("Decoração", _D, _VAR),
        # Nasceu em "Impostos e seguros" (migração d6f0ed375db0) — passou a viver aqui a pedido
        # do utilizador. Ver mover_categoria_de_grupo, chamada pela migração f57babb7aacc para
        # mover a categoria já existente numa BD antiga sem a duplicar; para uma BD nova (onde
        # esta lista já reflete o destino final), fica só a criação aqui, mesmo.
        CategoriaInicial("Seguro de vida", _D, _FIX),
    )),
    GrupoInicial("Alimentação", (
        CategoriaInicial("Supermercado", _D, _VAR),
        CategoriaInicial("Restaurantes", _D, _VAR),
        CategoriaInicial("Café", _D, _VAR),
    )),
    GrupoInicial("Transportes", (
        CategoriaInicial("Fuel Type", _D, _VAR),
        CategoriaInicial("Portagens", _D, _VAR),
        CategoriaInicial("Transportes públicos", _D, _VAR),
        CategoriaInicial("Manutenção auto", _D, _VAR),
        CategoriaInicial("Seguro auto", _D, _FIX),
        CategoriaInicial("Inspeção", _D, _VAR),
    )),
    GrupoInicial("Saúde", (
        CategoriaInicial("Consultas", _D, _VAR),
        CategoriaInicial("Medicamentos", _D, _VAR),
        CategoriaInicial("Dentista", _D, _VAR),
        CategoriaInicial("Seguro de saúde", _D, _FIX),
    )),
    GrupoInicial("Educação", (
        CategoriaInicial("Escola", _D, _FIX),
        CategoriaInicial("Material", _D, _VAR),
        CategoriaInicial("Atividades", _D, _VAR),
    )),
    GrupoInicial("Lazer", (
        CategoriaInicial("Subscrições", _D, _FIX),
        CategoriaInicial("Cultura", _D, _VAR),
        CategoriaInicial("Férias", _D, _VAR),
        CategoriaInicial("Desporto", _D, _VAR),
    )),
    GrupoInicial("Pessoal", (
        CategoriaInicial("Vestuário", _D, _VAR),
        CategoriaInicial("Cuidado pessoal", _D, _VAR),
        CategoriaInicial("Tabaco", _D, _VAR),
        CategoriaInicial("Eletrónica", _D, _VAR),
        CategoriaInicial("Outros pessoais", _D, _VAR),
    )),
    GrupoInicial("Impostos e seguros", (
        CategoriaInicial("IMI", _D, _FIX),
        CategoriaInicial("IRS", _D, _VAR),
        CategoriaInicial("IUC", _D, _FIX),
        CategoriaInicial("Outros impostos", _D, _VAR),
    )),
    GrupoInicial("Outros", (
        CategoriaInicial("Ofertas", _D, _VAR),
        CategoriaInicial("Doações", _D, _VAR),
        CategoriaInicial("Levantamento em numerário", _D, _VAR),
        CategoriaInicial("Não classificado", _D, _VAR),
    )),
    GrupoInicial("Rendimentos", (
        CategoriaInicial("Salário", _R, _REC),
        CategoriaInicial("Subsídio de alimentação", _R, _REC),
        # Rendimento garantido, mas cai em dois meses do ano. Contá-lo como recorrente tornava
        # esses dois meses artificialmente positivos e escondia, nos outros dez, que o dinheiro
        # existe. A margem responde "o meu salário chega?" (spec §3.2).
        CategoriaInicial("Subsídios de férias e Natal", _R, _EXT),
        CategoriaInicial("Prémios", _R, _EXT),
    )),
    GrupoInicial("Outros rendimentos", (
        CategoriaInicial("Dividendos", _R, _EXT),
        CategoriaInicial("Juros", _R, _EXT),
        CategoriaInicial("Rendas", _R, _REC),
        CategoriaInicial("Reembolsos", _R, _EXT),
        # É aqui que caem os adiantamentos de cartão (CASHADVANCE). Marcar este grupo como
        # extraordinário é o que os tira do rendimento base — a razão de ser desta spec.
        CategoriaInicial("Outros", _R, _EXT),
    )),
    GrupoInicial("Encargos financeiros", (
        CategoriaInicial("Juros de crédito", _D, _FIX),
        CategoriaInicial("Comissões bancárias", _D, _FIX),
        CategoriaInicial("Imposto de selo", _D, _FIX),
        # Fica variável e é irrelevante na prática: os movimentos desta categoria são
        # transferências com destino, e o eixo 1 decide por eles (financas/natureza.py).
        CategoriaInicial("Pagamento de crédito", _D, _VAR),
    )),
    GrupoInicial("Animais", (
        CategoriaInicial("Veterinário", _D, _VAR),
    )),
    GrupoInicial("Profissional", (
        CategoriaInicial("Profissional", _D, _VAR),
    )),
)

_META = MetaData()

_GRUPO = Table(
    "grupo_categoria",
    _META,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("nome", String(60)),
    Column("ordem", Integer),
    Column("ativo", Boolean),
)

_CATEGORIA = Table(
    "categoria",
    _META,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("grupo_id", UUID(as_uuid=True)),
    Column("nome", String(60)),
    Column("tipo", String(10)),
    Column("natureza", String(15)),
    Column("unidade_contador", String(10)),
    Column("ativo", Boolean),
)


def semear_categorias(connection: Connection) -> int:
    """Insere os grupos e categorias que ainda não existam. Devolve quantas categorias criou.

    Idempotente: assenta na existência do nome do grupo e do par (grupo, nome) da categoria,
    portanto correr duas vezes não duplica nada.

    Três migrações anteriores a `c4a7e2f81b6d` (`d6f0ed375db0`, `6422b67d58c8`,
    `f57babb7aacc`) chamam esta função numa base de dados NOVA, antes de a coluna `natureza`
    existir — só é criada por `c4a7e2f81b6d`, a última da cadeia. Sem esta deteção, o INSERT
    tentava escrever numa coluna inexistente e `alembic upgrade head` partia-se numa instalação
    de raiz (produção não é afetada: já está migrada incrementalmente, e a coluna já existe
    quando esta função corre a partir da migração desta feature). Quando a coluna ainda não
    existe, o INSERT omite `natureza`; `marcar_naturezas`, chamada por `c4a7e2f81b6d` logo a
    seguir a `semear_categorias`, preenche-a depois para qualquer linha que tenha ficado sem
    valor — incluindo as criadas aqui.
    """
    tem_coluna_natureza = "natureza" in {
        col["name"] for col in inspect(connection).get_columns("categoria")
    }

    criadas = 0

    for ordem, grupo in enumerate(GRUPOS_INICIAIS, start=1):
        grupo_id = connection.execute(
            select(_GRUPO.c.id).where(_GRUPO.c.nome == grupo.nome)
        ).scalar_one_or_none()

        if grupo_id is None:
            grupo_id = uuid.uuid4()
            connection.execute(
                insert(_GRUPO).values(id=grupo_id, nome=grupo.nome, ordem=ordem, ativo=True)
            )

        existentes = set(
            connection.execute(
                select(_CATEGORIA.c.nome).where(_CATEGORIA.c.grupo_id == grupo_id)
            ).scalars()
        )

        for categoria in grupo.categorias:
            if categoria.nome in existentes:
                continue
            valores = dict(
                id=uuid.uuid4(),
                grupo_id=grupo_id,
                nome=categoria.nome,
                tipo=categoria.tipo,
                unidade_contador=categoria.unidade_contador,
                ativo=True,
            )
            if tem_coluna_natureza:
                valores["natureza"] = categoria.natureza
            connection.execute(insert(_CATEGORIA).values(**valores))
            criadas += 1

    return criadas


def mover_categoria_de_grupo(
    connection: Connection, *, categoria_nome: str, grupo_origem_nome: str, grupo_destino_nome: str
) -> bool:
    """Move uma categoria já existente de um grupo para outro, preservando o seu id — ao
    contrário de semear_categorias (que só insere pares grupo+nome inexistentes), isto é para
    reclassificar uma categoria que já tem histórico (movimento_linha.categoria_id aponta para
    ela): um INSERT+DELETE duplicaria a categoria e órfão-aria esse histórico; um UPDATE ao
    grupo_id preserva-o intacto.

    Idempotente: se a categoria já não estiver no grupo de origem (porque já foi movida numa
    corrida anterior desta mesma função, ou porque nunca lá esteve), não faz nada. Devolve True
    se moveu, False caso contrário.
    """
    grupo_origem_id = connection.execute(
        select(_GRUPO.c.id).where(_GRUPO.c.nome == grupo_origem_nome)
    ).scalar_one_or_none()
    grupo_destino_id = connection.execute(
        select(_GRUPO.c.id).where(_GRUPO.c.nome == grupo_destino_nome)
    ).scalar_one_or_none()
    if grupo_origem_id is None or grupo_destino_id is None:
        return False

    resultado = connection.execute(
        update(_CATEGORIA)
        .where(_CATEGORIA.c.nome == categoria_nome, _CATEGORIA.c.grupo_id == grupo_origem_id)
        .values(grupo_id=grupo_destino_id)
    )
    return resultado.rowcount > 0


def marcar_naturezas(connection: Connection) -> int:
    """Marca a `natureza` das categorias já existentes, por NOME e ignorando o grupo.

    Devolve quantas linhas atualizou.

    Ignorar o grupo é deliberado: em produção existem `Imposto de selo` e `Juros de crédito`
    tanto em "Encargos financeiros" (do seed) como em "Habitação" (criadas pelo utilizador), e
    marcar por (grupo, nome) deixava as segundas por marcar. Nenhum nome do seed pede naturezas
    diferentes conforme o grupo, por isso o nome é chave suficiente.

    As categorias que não constam do seed ficam no default seguro do §3.3 da spec: receita →
    `extraordinario`, despesa → `variavel`. Os defaults são assimétricos porque as consequências
    são: do lado da receita, não contar como fiável o que não se conhece é o erro seguro (e é o
    oposto do que a app fazia); do lado da despesa, `fixa` e `variavel` são ambas subtraídas, por
    isso o default só afeta a repartição, nunca o total.
    """
    por_nome = {
        categoria.nome: categoria.natureza
        for grupo in GRUPOS_INICIAIS
        for categoria in grupo.categorias
    }

    atualizadas = 0
    for nome, natureza in por_nome.items():
        resultado = connection.execute(
            update(_CATEGORIA).where(_CATEGORIA.c.nome == nome).values(natureza=natureza)
        )
        atualizadas += resultado.rowcount

    for tipo, default in (("receita", "extraordinario"), ("despesa", "variavel")):
        resultado = connection.execute(
            update(_CATEGORIA)
            .where(_CATEGORIA.c.tipo == tipo, _CATEGORIA.c.nome.not_in(list(por_nome)))
            .values(natureza=default)
        )
        atualizadas += resultado.rowcount

    return atualizadas
