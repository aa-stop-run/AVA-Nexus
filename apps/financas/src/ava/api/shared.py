import uuid
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria
from ava.repositories import documento_repo, fila_repo, obrigacao_repo

templates = Jinja2Templates(directory="src/ava/templates")


def format_pt(value):
    if value is None:
        return ""
    return "{:,.2f}".format(float(value)).replace(",", "X").replace(".", ",").replace("X", ".")


templates.env.filters["format_pt"] = format_pt


# Rótulos e ordem de apresentação das categorias de dívida (ver Conta.categoria_divida).
CATEGORIA_DIVIDA_LABELS = {
    "habitacao": "Habitação",
    "pessoal": "Crédito Pessoal",
    "automovel": "Crédito Automóvel",
    "cartao": "Cartão de Crédito",
    "obras": "Crédito para Obras",
    "consolidado": "Crédito Consolidado",
    "outro": "Outro",
}

# Rótulos e ordem de apresentação das categorias de investimento (ver Conta.categoria_investimento).
CATEGORIA_INVESTIMENTO_LABELS = {
    "ppr": "PPR",
    "etf": "ETF",
    "acoes": "Ações",
    "obrigacoes": "Obrigações",
    "outro": "Outro",
}

# Cores cíclicas para as categorias dentro de um grupo, na visão "Despesas por categoria" do
# dashboard — não precisam de ser globalmente únicas (cada grupo é um bloco visual à parte),
# só distintas dentro do mesmo grupo. Se um grupo tiver mais categorias do que cores, repete.
_PALETA_CATEGORIAS = (
    "#7c3aed",
    "#2563eb",
    "#0891b2",
    "#db2777",
    "#16a34a",
    "#d97706",
    "#0d9488",
    "#ea580c",
    "#4f46e5",
)


def _despesas_por_grupo(
    totais: list[tuple[GrupoCategoria, Categoria, Decimal]], total_geral: Decimal
) -> list[dict]:
    """Reagrupa a lista plana (grupo, categoria, total) de movimento_repo.totais_por_categoria
    (já ordenada por total desc) numa visão a dois níveis: grupo (visão macro, % do total geral)
    > categorias (cor cíclica + % dentro do PRÓPRIO grupo, não do total geral — para o peso
    relativo de cada categoria ficar claro independentemente de quão grande é o grupo face aos
    outros)."""
    grupos: dict[uuid.UUID, dict] = {}
    for grupo, categoria, total in totais:
        entrada = grupos.setdefault(
            grupo.id, {"grupo": grupo, "total": Decimal("0"), "categorias": []}
        )
        entrada["total"] += total
        entrada["categorias"].append({"categoria": categoria, "total": total})

    lista = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
    for entrada in lista:
        entrada["percent"] = float(entrada["total"] / total_geral * 100) if total_geral else 0.0
        entrada["categorias"].sort(key=lambda c: c["total"], reverse=True)
        for indice, item in enumerate(entrada["categorias"]):
            item["percent"] = (
                float(item["total"] / entrada["total"] * 100) if entrada["total"] else 0.0
            )
            item["cor"] = _PALETA_CATEGORIAS[indice % len(_PALETA_CATEGORIAS)]

    return lista


async def _contar_alertas(session: AsyncSession) -> int:
    documentos = await documento_repo.listar_por_estado(session, "revisao_manual")
    obrigacoes = await obrigacao_repo.listar_pendentes(session)
    falhas = await fila_repo.listar_com_erro(session)
    return len(documentos) + len(obrigacoes) + len(falhas)


def _parse_filtros_movimentos(
    *,
    busca: str | None,
    valor_min: str | None,
    valor_max: str | None,
    data_inicio: str | None,
    data_fim: str | None,
    mes_ano: str | None = None,
    tipo_movimento: str | None = None,
) -> dict:
    """Interpreta os filtros vindos da query string de /movimentos e /patrimonio/contas/{id}
    (todos em texto, todos opcionais). Um valor malformado (ex. "abc" em valor_min, uma data
    fora de ISO) é ignorado silenciosamente — o filtro correspondente simplesmente não se aplica
    — em vez de rebentar a página com um 422 por um erro de digitação."""
    filtros: dict = {}
    if busca and busca.strip():
        filtros["busca"] = busca.strip()

    for chave, valor in (("valor_min", valor_min), ("valor_max", valor_max)):
        if valor and valor.strip():
            try:
                filtros[chave] = Decimal(valor.strip().replace(",", "."))
            except InvalidOperation:
                pass

    for chave, valor in (("data_inicio", data_inicio), ("data_fim", data_fim)):
        if valor and valor.strip():
            try:
                filtros[chave] = date.fromisoformat(valor.strip())
            except ValueError:
                pass

    if mes_ano and mes_ano.strip():
        try:
            # yyyy-mm
            y, m = map(int, mes_ano.strip().split("-"))
            if "data_inicio" not in filtros:
                filtros["data_inicio"] = date(y, m, 1)
            if "data_fim" not in filtros:
                _, last_day = monthrange(y, m)
                filtros["data_fim"] = date(y, m, last_day)
        except Exception:
            pass

    if tipo_movimento and tipo_movimento.strip():
        filtros["tipo_movimento"] = tipo_movimento.strip()

    return filtros
