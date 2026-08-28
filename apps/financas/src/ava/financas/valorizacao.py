"""Valor projetado de um ativo numa data, a partir da avaliação observada mais recente.

Nada aqui é gravado. A projeção é sempre calculada na leitura e sempre apresentada marcada como
estimativa (ver a spec 2026-08-05, §2): um número inventado com ar de facto é pior do que um
número em falta.

Módulo puro de propósito — sem sessão, sem I/O. A matemática fica testável sem Postgres, e quem
percorre muitas datas (o gráfico de património) pode chamá-la em ciclo sem custo.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

# Taxa de variação anual por tipo de ativo, como fração. Palpites razoáveis para o mercado
# português, não valores medidos — por isso `Ativo.taxa_anual` existe para os sobrepor.
# "veiculo" é o valor legado escrito pela migração e1a2b3c4d5e6 (ver ativo_repo.TIPOS_VEICULO).
TAXAS_POR_TIPO: dict[str, Decimal] = {
    "carro": Decimal("-0.15"),
    "mota": Decimal("-0.12"),
    "veiculo": Decimal("-0.15"),
    "casa": Decimal("0.02"),
    "outro": Decimal("0"),
}

_DIAS_POR_ANO = Decimal("365.25")
_CENTIMOS = Decimal("0.01")


class ValorAtivo(NamedTuple):
    """Valor de um ativo numa data, com a proveniência que o UI precisa de mostrar."""

    valor: Decimal
    e_projetado: bool
    data_observacao: date


def taxa_de(tipo: str, taxa_anual: Decimal | None) -> Decimal:
    """A taxa a aplicar: a do ativo se estiver definida, senão a omissão do tipo.

    O teste é `is None` e não um `or`: Decimal("0") é falsy, e um utilizador que declare
    explicitamente "este bem não deprecia" veria a sua escolha substituída pela omissão do tipo.

    Tipo desconhecido devolve 0 — nunca se inventa uma taxa para uma categoria não prevista.
    """
    if taxa_anual is not None:
        return taxa_anual
    return TAXAS_POR_TIPO.get(tipo, Decimal("0"))


def projetar(
    valor_observado: Decimal, data_observacao: date, data_alvo: date, taxa: Decimal
) -> Decimal:
    """Aplica a taxa composta entre as duas datas. Arredonda a cêntimos.

    `data_alvo` anterior a `data_observacao` é erro de programação, não um caso a tratar: quem
    chama tem de escolher primeiro a observação correta (ativo_valor_repo.obter_valor_em_data),
    e projetar para trás reescreveria um passado que já foi observado.
    """
    if data_alvo < data_observacao:
        raise ValueError(
            f"data_alvo {data_alvo} é anterior à observação {data_observacao} — "
            "escolha a observação correta antes de projetar"
        )

    anos = Decimal((data_alvo - data_observacao).days) / _DIAS_POR_ANO
    # Potência inteiramente em Decimal — sem passar por float. Uma taxa < -1 dá base negativa
    # (1 + taxa < 0), que não tem potência real; Decimal levanta InvalidOperation, o
    # comportamento correto para um valor sem sentido. Em taxa == -1 a base é exatamente 0, e
    # 0 ** anos devolve 0 sem erro — o limiar é "<", não "<=".
    fator = (1 + taxa) ** anos
    return (valor_observado * fator).quantize(_CENTIMOS, rounding=ROUND_HALF_UP)
