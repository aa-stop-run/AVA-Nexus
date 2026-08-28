"""Módulo de compatibilidade e agregação dos sub-routers da interface web.

Os endpoints foram divididos nos seguintes módulos especializados:
- `ava.api.home`: Rotas da visão geral e analítica (/, /insights, /prazos)
- `ava.api.patrimonio`: Rotas de património e saldos (/patrimonio, /patrimonio/contas/{id}, /contas/novo)
- `ava.api.ativos`: Rotas de bens físicos (/patrimonio/ativos/*, /ativos/novo)
- `ava.api.movimentos`: Rotas de movimentos, filtros, registo e ações HTMX
- `ava.api.alertas`: Rotas operacionais e de revisão (/alertas, /falhas, /revisao)
- `ava.api.shared`: Templates Jinja2, filtros e helpers comuns
"""

from fastapi import APIRouter

from ava.api.alertas import router as alertas_router
from ava.api.ativos import router as ativos_router
from ava.api.home import router as home_router
from ava.api.movimentos import router as movimentos_router
from ava.api.patrimonio import router as patrimonio_router
from ava.api.shared import (
    CATEGORIA_DIVIDA_LABELS,
    CATEGORIA_INVESTIMENTO_LABELS,
    _PALETA_CATEGORIAS,
    _contar_alertas,
    _despesas_por_grupo,
    _parse_filtros_movimentos,
    format_pt,
    templates,
)

# Router agregado para retrocompatibilidade
router = APIRouter(tags=["dashboard"])
router.include_router(home_router)
router.include_router(patrimonio_router)
router.include_router(ativos_router)
router.include_router(movimentos_router)
router.include_router(alertas_router)

__all__ = [
    "router",
    "templates",
    "format_pt",
    "CATEGORIA_DIVIDA_LABELS",
    "CATEGORIA_INVESTIMENTO_LABELS",
    "_PALETA_CATEGORIAS",
    "_despesas_por_grupo",
    "_contar_alertas",
    "_parse_filtros_movimentos",
]
