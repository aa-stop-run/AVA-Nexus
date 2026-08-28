from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass
class AbastecimentoInput:
    data: date
    km: int
    quantidade: Decimal
    preco_total: Decimal
    tanque_cheio: bool = True


def calcular_medias_abastecimentos(
    abastecimentos: list[AbastecimentoInput],
) -> dict[str, Any]:
    """Calcula estatísticas de consumo, médias L/100km e custo por quilómetro."""
    if not abastecimentos:
        return {
            "consumo_medio_geral": None,
            "total_km_percorridos": 0,
            "total_litros": Decimal("0.00"),
            "total_gasto": Decimal("0.00"),
            "custo_por_km": None,
            "historico_medias": [],
        }

    # Ordena cronologicamente
    ordenados = sorted(abastecimentos, key=lambda a: (a.data, a.km))
    total_gasto = sum((a.preco_total for a in ordenados), Decimal("0.00"))
    total_litros = sum((a.quantidade for a in ordenados), Decimal("0.00"))

    if len(ordenados) < 2:
        return {
            "consumo_medio_geral": None,
            "total_km_percorridos": 0,
            "total_litros": total_litros,
            "total_gasto": total_gasto,
            "custo_por_km": None,
            "historico_medias": [],
        }

    historico = []
    total_km_consumo = 0
    total_litros_consumo = Decimal("0.00")

    for i in range(1, len(ordenados)):
        anterior = ordenados[i - 1]
        atual = ordenados[i]
        delta_km = atual.km - anterior.km

        if delta_km > 0 and atual.tanque_cheio:
            consumo_trecho = ((atual.quantidade / Decimal(delta_km)) * Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            custo_km_trecho = (atual.preco_total / Decimal(delta_km)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            historico.append(
                {
                    "data": atual.data,
                    "delta_km": delta_km,
                    "quantidade": atual.quantidade,
                    "consumo_l100km": consumo_trecho,
                    "custo_km": custo_km_trecho,
                }
            )
            total_km_consumo += delta_km
            total_litros_consumo += atual.quantidade

    consumo_medio_geral = None
    if total_km_consumo > 0 and total_litros_consumo > Decimal("0"):
        consumo_medio_geral = (
            (total_litros_consumo / Decimal(total_km_consumo)) * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total_km_total = ordenados[-1].km - ordenados[0].km
    custo_por_km = None
    if total_km_total > 0:
        custo_por_km = (
            (total_gasto - ordenados[0].preco_total) / Decimal(total_km_total)
        ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    return {
        "consumo_medio_geral": consumo_medio_geral,
        "total_km_percorridos": total_km_total,
        "total_litros": total_litros,
        "total_gasto": total_gasto,
        "custo_por_km": custo_por_km,
        "historico_medias": historico,
    }
