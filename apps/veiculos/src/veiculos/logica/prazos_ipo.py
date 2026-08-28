import calendar
from datetime import date, timedelta
from typing import Any

MESES_PT = [
    "",
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]


def calcular_mes_iuc(mes_matricula: int | None) -> str:
    if mes_matricula and 1 <= mes_matricula <= 12:
        return MESES_PT[mes_matricula]
    return "N/D"


def calcular_proxima_ipo(
    *,
    ano_matricula: int | None,
    mes_matricula: int | None,
    dia_matricula: int | None = None,
    tipo: str = "carro",
    referencia: date | None = None,
) -> date | None:
    """Calcula a data da próxima inspeção obrigatória segundo as regras legais de PT."""
    if not ano_matricula or not mes_matricula:
        return None

    hoje = referencia or date.today()
    dia = dia_matricula or 1

    # Anos de inspeção para ligeiros de passageiros (carro/mota >250cc):
    # 4 anos, 6 anos, 8 anos e depois anualmente.
    anos_inspecao = [ano_matricula + 4, ano_matricula + 6, ano_matricula + 8]
    ano_max = max(hoje.year + 2, ano_matricula + 10)
    for a in range(ano_matricula + 9, ano_max + 1):
        anos_inspecao.append(a)

    for a in anos_inspecao:
        max_dias = calendar.monthrange(a, mes_matricula)[1]
        data_ipo = date(a, mes_matricula, min(dia, max_dias))
        if data_ipo >= hoje:
            return data_ipo

    prox_ano = anos_inspecao[-1] + 1
    return date(prox_ano, mes_matricula, min(dia, calendar.monthrange(prox_ano, mes_matricula)[1]))


def verificar_estado_prazos(
    *,
    data_proxima_ipo: date | None,
    mes_matricula_iuc: int | None,
    data_fim_seguro: date | None,
    hoje: date | None = None,
) -> dict[str, Any]:
    """Avalia a proximidade dos prazos legais para gerar badges e alertas."""
    h = hoje or date.today()

    # IPO
    ipo_dias = (data_proxima_ipo - h).days if data_proxima_ipo else None
    # Alerta se faltar menos de 60 dias para a IPO (a janela legal de inspeção abre 3 meses antes)
    ipo_alerta = ipo_dias is not None and ipo_dias <= 60
    ipo_urgente = ipo_dias is not None and ipo_dias <= 15

    # IUC
    iuc_mes_atual = mes_matricula_iuc is not None and mes_matricula_iuc == h.month
    iuc_proximo = mes_matricula_iuc is not None and (mes_matricula_iuc == (h.month + 1 if h.month < 12 else 1))

    # Seguro
    seguro_dias = (data_fim_seguro - h).days if data_fim_seguro else None
    seguro_alerta = seguro_dias is not None and seguro_dias <= 30
    seguro_urgente = seguro_dias is not None and seguro_dias <= 7

    return {
        "ipo_dias_restantes": ipo_dias,
        "ipo_alerta": ipo_alerta,
        "ipo_urgente": ipo_urgente,
        "iuc_mes_atual": iuc_mes_atual,
        "iuc_proximo": iuc_proximo,
        "iuc_mes_nome": calcular_mes_iuc(mes_matricula_iuc),
        "seguro_dias_restantes": seguro_dias,
        "seguro_alerta": seguro_alerta,
        "seguro_urgente": seguro_urgente,
    }
