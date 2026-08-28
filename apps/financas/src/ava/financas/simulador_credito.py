import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class CenarioAmortizacao:
    nova_prestacao: Decimal
    poupanca_mensal: Decimal
    novo_prazo_meses: int
    meses_poupados: int
    total_juros: Decimal
    poupanca_total_juros: Decimal


@dataclass(frozen=True)
class ResultadoSimulacao:
    capital_atual: Decimal
    taxa_anual: Decimal
    prazo_meses_atual: int
    prestacao_atual: Decimal
    total_juros_atual: Decimal
    valor_amortizar: Decimal
    comissao_bancaria: Decimal
    novo_capital: Decimal
    cenario_reduzir_prestacao: CenarioAmortizacao
    cenario_reduzir_prazo: CenarioAmortizacao


def _arredondar(valor: Decimal | float) -> Decimal:
    if isinstance(valor, float):
        valor = Decimal(str(round(valor, 4)))
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_prestacao_mensal(
    capital: Decimal, taxa_anual_pct: Decimal, prazo_meses: int
) -> Decimal:
    if capital <= 0 or prazo_meses <= 0:
        return Decimal("0.00")
    if taxa_anual_pct <= 0:
        return _arredondar(capital / prazo_meses)

    r = float(taxa_anual_pct / 100 / 12)
    c = float(capital)
    n = prazo_meses
    p = c * (r / (1.0 - math.pow(1.0 + r, -n)))
    return _arredondar(p)


def calcular_amortizacao(
    *,
    capital_atual: Decimal,
    taxa_anual: Decimal,
    prazo_meses: int,
    valor_amortizar: Decimal,
    taxa_comissao: Decimal = Decimal("0.5"),
) -> ResultadoSimulacao:
    if capital_atual <= 0:
        raise ValueError("Capital em dívida tem de ser positivo")
    if prazo_meses <= 0:
        raise ValueError("Prazo em meses tem de ser positivo")
    if valor_amortizar <= 0:
        raise ValueError("Valor a amortizar tem de ser positivo")
    if valor_amortizar > capital_atual:
        raise ValueError("Valor a amortizar não pode ser superior ao capital em dívida")
    if taxa_anual < 0:
        raise ValueError("Taxa anual não pode ser negativa")
    if taxa_comissao < 0:
        raise ValueError("Taxa de comissão não pode ser negativa")

    p_atual = calcular_prestacao_mensal(capital_atual, taxa_anual, prazo_meses)
    juros_totais_atual = _arredondar((p_atual * prazo_meses) - capital_atual)

    comissao = _arredondar(valor_amortizar * (taxa_comissao / Decimal("100")))
    novo_capital = capital_atual - valor_amortizar

    # Cenário 1: Reduzir Prestação (mantém prazo_meses)
    p_cenario1 = calcular_prestacao_mensal(novo_capital, taxa_anual, prazo_meses)
    poupanca_mensal_1 = p_atual - p_cenario1
    juros_cenario1 = _arredondar((p_cenario1 * prazo_meses) - novo_capital)
    poupanca_total_1 = _arredondar(juros_totais_atual - juros_cenario1 - comissao)

    cenario1 = CenarioAmortizacao(
        nova_prestacao=p_cenario1,
        poupanca_mensal=poupanca_mensal_1,
        novo_prazo_meses=prazo_meses,
        meses_poupados=0,
        total_juros=juros_cenario1,
        poupanca_total_juros=poupanca_total_1,
    )

    # Cenário 2: Reduzir Prazo (mantém prestação p_atual)
    if taxa_anual <= 0:
        n_cenario2 = math.ceil(float(novo_capital / p_atual))
        juros_cenario2 = Decimal("0.00")
    else:
        r = float(taxa_anual / 100 / 12)
        c_novo = float(novo_capital)
        p_val = float(p_atual)
        termo = 1.0 - (c_novo * r / p_val)
        if termo <= 0:
            n_cenario2 = 1
        else:
            n_cenario2 = math.ceil(-math.log(termo) / math.log(1.0 + r))
        juros_cenario2 = _arredondar((p_atual * n_cenario2) - novo_capital)

    meses_poupados_2 = max(0, prazo_meses - n_cenario2)
    poupanca_total_2 = _arredondar(juros_totais_atual - juros_cenario2 - comissao)

    cenario2 = CenarioAmortizacao(
        nova_prestacao=p_atual,
        poupanca_mensal=Decimal("0.00"),
        novo_prazo_meses=n_cenario2,
        meses_poupados=meses_poupados_2,
        total_juros=juros_cenario2,
        poupanca_total_juros=poupanca_total_2,
    )

    return ResultadoSimulacao(
        capital_atual=capital_atual,
        taxa_anual=taxa_anual,
        prazo_meses_atual=prazo_meses,
        prestacao_atual=p_atual,
        total_juros_atual=juros_totais_atual,
        valor_amortizar=valor_amortizar,
        comissao_bancaria=comissao,
        novo_capital=novo_capital,
        cenario_reduzir_prestacao=cenario1,
        cenario_reduzir_prazo=cenario2,
    )
