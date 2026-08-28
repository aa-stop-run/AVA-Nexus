from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LinhaFatura(BaseModel):
    descricao: str
    valor: Decimal


class Consumo(BaseModel):
    quantidade: Decimal
    unidade: str  # "kWh" | "m3"
    periodo_inicio: date
    periodo_fim: date


class FaturaExtraida(BaseModel):
    fornecedor_nome: str
    nif_emissor: str | None = None
    iban: str | None = None
    valor_total: Decimal
    data_limite_pagamento: date
    linhas: list[LinhaFatura] = Field(default_factory=list)
    consumo: Consumo | None = None
    ativo_relacionado: str | None = Field(
        default=None,
        description="Se a fatura diz respeito a um ativo específico (ex: matrícula de carro, imóvel).",
    )
