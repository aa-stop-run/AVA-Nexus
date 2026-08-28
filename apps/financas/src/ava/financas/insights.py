"""Insights financeiros: pequenos textos gerados a partir de dados já existentes na app.

Módulo puro de propósito, mesma razão de `saldos.py`/`natureza.py`: cada `calcular_X` recebe
dados já lidos da base (não uma sessão) e devolve uma lista de `Insight` — testável sem
Postgres. A leitura de dados e a orquestração entre calculadores vivem em
`ava.repositories.insights_repo`.

Ver spec docs/superpowers/specs/2026-08-20-insights-financeiros-design.md.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from ava.financas.formatacao import formatar_valor_pt

if TYPE_CHECKING:
    from ava.models.recorrente import Recorrente

# Variação RELATIVA mínima (1% do valor esperado) para a mensalidade de um recorrente ser
# considerada "mudou" -- abaixo disto é ruído de cêntimos, não uma subida/descida real. É uma
# fração, não euros: numa renda de 800€, 1% são 8€; numa subscrição de 5€, 1% são 5 cêntimos --
# a mesma fração pesa de forma bem diferente consoante o valor do recorrente (achado da revisão
# final de 2026-08-20, o nome antigo `_LIMIAR_MENSALIDADE` lia-se como se fosse um valor em
# euros).
_LIMIAR_MENSALIDADE_RELATIVO = Decimal("0.01")

# Diferença ABSOLUTA mínima (em euros) para a margem estrutural ser considerada "mudou" face à
# média dos 3 meses anteriores. Absoluto, não percentual: a margem pode ser negativa ou cruzar
# zero, onde uma percentagem perde o sentido (ver spec §6.3 -- o próprio exemplo já usa euros,
# não %).
_LIMIAR_MARGEM_ABSOLUTO = Decimal("50")

# Variação RELATIVA mínima (20%) para um grupo de despesa ser considerado "mudou" face à média
# dos 3 meses anteriores (spec §6.2). Percentual, não absoluto: ao contrário da margem, um total
# de despesas nunca é negativo, por isso não há problema de base a cruzar zero.
_LIMIAR_CATEGORIA_RELATIVO = Decimal("0.2")

# Taxa de recuperação abaixo da qual o insight de ressarcimento chama a atenção (spec §6.4) --
# acima disto é informativo (tom neutro), não um alerta.
_LIMIAR_RECUPERACAO_BAIXA = Decimal("0.5")

# Janela de extrapolação da projeção de poupança (spec §6.5) -- fixa, não "meses restantes do
# ano civil": essa alternativa encolhia o horizonte à medida que o ano avançava e reiniciava
# todos os Janeiros para 12 meses, uma mudança brusca sem nada ter mudado na poupança real
# (decisão do utilizador, 2026-08-20).
_JANELA_PROJECAO_MESES = 6

# Média mensal mínima (absoluta, em euros) para a projeção de poupança valer a pena mostrar --
# abaixo disto a extrapolação é ruído, não uma tendência.
_LIMIAR_PROJECAO_MENSAL = Decimal("50")


# Limiares de cobertura do fundo de emergência (runway em meses).
_LIMIAR_RUNWAY_CONFORTO_MINIMO = Decimal("3.0")
_LIMIAR_RUNWAY_ESSENCIAL_MINIMO = Decimal("6.0")
_LIMIAR_RUNWAY_CONFORTO_SOLIDO = Decimal("6.0")

# Variação mínima relativa (20%) e absoluta (25€) para anomalia em utilities.
_LIMIAR_UTILITIES_RELATIVO = Decimal("0.20")
_LIMIAR_UTILITIES_ABSOLUTO = Decimal("25.00")

# Limiares do rácio de custos fixos face ao rendimento habitual
_LIMIAR_CUSTOS_FIXOS_ALTO = Decimal("0.50")
_LIMIAR_CUSTOS_FIXOS_BAIXO = Decimal("0.35")




@dataclass(frozen=True)
class Insight:
    tipo: str                                  # chave estável, ex. "mensalidade:<recorrente_id>"
    titulo: str                                # "A tua mensalidade da Netflix subiu"
    descricao: str                             # frase curta com o porquê / os números
    tom: str                                   # "atencao" | "positivo" | "neutro"
    area: str                                  # "despesas" | "margem" | "saude" | "patrimonio"
    valor: str | None = None                   # já formatado, ex. "+3,00 €"
    link: str | None = None                    # para onde apontar ao clicar
    serie: tuple[Decimal, ...] | None = None   # só nos insights de tendência, para o sparkline


def calcular_mensalidade(
    pares: list[tuple["Recorrente", Decimal | None]]
) -> list[Insight]:
    """Um insight por `Recorrente` cujo movimento real (`valor_real`, já encontrado por
    `insights_repo`) se afaste do valor esperado além de `_LIMIAR_MENSALIDADE_RELATIVO`.

    `pares` já vem filtrado e casado por `insights_repo.listar_insights` -- esta função não sabe
    nada de contas, datas nem sessões, só compara dois números.
    """
    insights: list[Insight] = []
    for recorrente, valor_real in pares:
        if valor_real is None or recorrente.valor == 0:
            continue
        variacao = abs(valor_real - recorrente.valor) / recorrente.valor
        if variacao <= _LIMIAR_MENSALIDADE_RELATIVO:
            continue
        subiu = valor_real > recorrente.valor
        diferenca = abs(valor_real - recorrente.valor)
        insights.append(Insight(
            tipo=f"mensalidade:{recorrente.id}",
            titulo=f"A tua mensalidade de {recorrente.descricao} {'subiu' if subiu else 'desceu'}",
            descricao=f"De {formatar_valor_pt(recorrente.valor)} € para {formatar_valor_pt(valor_real)} €",
            tom="atencao" if subiu else "positivo",
            area="despesas",
            valor=f"{'+' if subiu else '-'}{formatar_valor_pt(diferenca)} €",
        ))
    return insights


def calcular_tendencia_margem(margens_6_meses: list[Decimal]) -> list[Insight]:
    """Compara a margem estrutural do mês mais recente com a média dos 3 meses anteriores.

    `margens_6_meses`: os últimos 6 meses, mais antigo primeiro, terminando no mês em avaliação
    (já lidos por `insights_repo._margens_dos_ultimos_6_meses`). Só usa os últimos 4 para o
    gatilho -- os 6 inteiros ficam em `serie`, para o sparkline mostrar mais contexto do que o
    que decide se o insight aparece.
    """
    if len(margens_6_meses) < 4:
        return []
    atual = margens_6_meses[-1]
    anteriores = margens_6_meses[-4:-1]
    media_anterior = sum(anteriores) / len(anteriores)
    diferenca = atual - media_anterior
    if abs(diferenca) <= _LIMIAR_MARGEM_ABSOLUTO:
        return []
    melhorou = diferenca > 0
    sinal = "+" if melhorou else "-"
    valor_formatado = f"{sinal}{formatar_valor_pt(abs(diferenca))} €"
    return [Insight(
        tipo="tendencia_margem",
        titulo=(
            "A tua margem estrutural está a melhorar" if melhorou
            else "A tua margem estrutural está a piorar"
        ),
        # Só a frase, sem repetir o valor -- a coluna `valor` já mostra o número (achado da
        # revisão final: a versão anterior mostrava o mesmo "+210,00 €" duas vezes na mesma
        # linha, ao contrário do insight de mensalidade, onde descricao e valor se complementam).
        descricao="Face à média dos últimos 3 meses.",
        tom="positivo" if melhorou else "atencao",
        area="margem",
        valor=valor_formatado,
        serie=tuple(margens_6_meses),
    )]


def calcular_tendencia_categoria(dados: list[tuple[str, list[Decimal]]]) -> list[Insight]:
    """Um insight por grupo de despesa cuja variação (mês atual vs. média dos 3 anteriores)
    passe ±20%.

    `dados`: uma entrada por grupo (nome do grupo, últimos 6 meses de totais, mais antigo
    primeiro, terminando no mês em avaliação) -- já lidos por
    `insights_repo._totais_por_grupo_ultimos_6_meses`.

    Funde duas ideias do backlog original (spec §6.2): "tendência por categoria" e "orçamento:
    média dos últimos 6 meses vs. este mês" eram a mesma pergunta feita duas vezes.

    Um grupo sem despesa nenhuma nos 3 meses anteriores (média = 0) não tem tendência para medir
    -- é uma categoria nova este mês, não uma subida, e uma percentagem sobre zero não faz
    sentido. Fica fora do âmbito deste insight.
    """
    insights: list[Insight] = []
    for nome_grupo, totais_6_meses in dados:
        if len(totais_6_meses) < 4:
            continue
        atual = totais_6_meses[-1]
        anteriores = totais_6_meses[-4:-1]
        media_anterior = sum(anteriores) / len(anteriores)
        if media_anterior == 0:
            continue
        variacao = (atual - media_anterior) / media_anterior
        if abs(variacao) <= _LIMIAR_CATEGORIA_RELATIVO:
            continue
        subiu = variacao > 0
        percentagem = abs(variacao) * 100
        insights.append(Insight(
            tipo=f"tendencia_categoria:{nome_grupo}",
            titulo=f"{nome_grupo} {'subiu' if subiu else 'desceu'} {percentagem:.0f}% este mês",
            descricao=f"{formatar_valor_pt(atual)} € vs. média de {formatar_valor_pt(media_anterior)} €",
            tom="atencao" if subiu else "positivo",
            area="despesas",
            valor=f"{'+' if subiu else '-'}{percentagem:.0f}%",
            serie=tuple(totais_6_meses),
        ))
    return insights


def calcular_recuperacao_ressarcimento(resumos: list[tuple[Decimal, Decimal]]) -> list[Insight]:
    """Que fração das despesas de saúde recentes (últimos 90 dias) já foi reembolsada.

    `resumos`: um (despesas, reembolsos) por grupo de ressarcimento -- já lidos por
    `insights_repo._resumos_ressarcimento_recentes` a partir de `ressarcimento_repo.listar_recentes`.
    Um único insight agregado, não um por grupo: a pergunta é "quanto já recuperei ao todo",
    não "como está cada reembolso" (essa já tem o próprio ecrã, `_ressarcimento_cell.html`).

    Sem despesas nenhumas no período (grupos vazios, ou só com o reembolso já ligado e a despesa
    ainda por vir) não há taxa nenhuma para mostrar -- 0/0 não é "0% recuperado", é "não há nada
    para recuperar ainda".
    """
    total_despesas = sum((despesas for despesas, _reembolsos in resumos), Decimal("0"))
    if total_despesas <= 0:
        return []
    total_reembolsos = sum((reembolsos for _despesas, reembolsos in resumos), Decimal("0"))
    taxa = total_reembolsos / total_despesas
    percentagem = taxa * 100
    return [Insight(
        tipo="recuperacao_ressarcimento",
        titulo=f"Recuperaste {percentagem:.0f}% das tuas despesas de saúde",
        descricao=(
            f"Nos últimos 90 dias: {formatar_valor_pt(total_reembolsos)} € de "
            f"{formatar_valor_pt(total_despesas)} €"
        ),
        tom="atencao" if taxa < _LIMIAR_RECUPERACAO_BAIXA else "neutro",
        area="saude",
        valor=f"{percentagem:.0f}%",
    )]


def calcular_projecao_poupanca(poupancas_6_meses: list[Decimal]) -> list[Insight]:
    """Extrapolação linear simples: média da poupança dos últimos 3 meses × janela fixa de
    `_JANELA_PROJECAO_MESES` meses (spec §6.5).

    `poupancas_6_meses`: os últimos 6 meses de `margem.poupanca`, mais antigo primeiro,
    terminando no mês em avaliação -- mesma forma de `margens_6_meses` em
    `calcular_tendencia_margem`, já lidos por `insights_repo._poupancas_dos_ultimos_6_meses`. Só
    os últimos 3 entram na média (não os 6): mesma janela de "meses recentes" que os outros
    insights de tendência já usam, mais reativo a uma mudança genuína de ritmo do que diluí-la
    em 6 meses.

    A única ideia "alto esforço" do backlog original (spec §8) -- se a poupança recente for
    negativa, a extrapolação é um défice, não uma poupança, e o insight diz isso sem rodeios em
    vez de mostrar um número negativo como se fosse dinheiro guardado.
    """
    if len(poupancas_6_meses) < 3:
        return []
    recentes = poupancas_6_meses[-3:]
    media = sum(recentes) / len(recentes)
    if abs(media) <= _LIMIAR_PROJECAO_MENSAL:
        return []
    projecao = media * _JANELA_PROJECAO_MESES
    positiva = projecao > 0
    valor_formatado = f"{'+' if positiva else '-'}{formatar_valor_pt(abs(projecao))} €"
    titulo = (
        f"A este ritmo, em {_JANELA_PROJECAO_MESES} meses terás guardado mais "
        f"{formatar_valor_pt(abs(projecao))} €"
        if positiva else
        f"A este ritmo, em {_JANELA_PROJECAO_MESES} meses terás um défice de "
        f"{formatar_valor_pt(abs(projecao))} €"
    )
    return [Insight(
        tipo="projecao_poupanca",
        titulo=titulo,
        descricao=f"Com base na média dos últimos 3 meses ({formatar_valor_pt(media)} €/mês)",
        tom="positivo" if positiva else "atencao",
        area="margem",
        valor=valor_formatado,
    )]


def _formatar_meses_pt(meses: Decimal) -> str:
    quantizado = meses.quantize(Decimal("0.1"))
    return f"{quantizado:f}".replace(".", ",")


def calcular_runway_emergencia(
    *,
    liquidez_total: Decimal,
    despesa_media_global: Decimal,
    despesa_essencial_mensal: Decimal,
) -> list[Insight]:
    """Calcula a autonomia do fundo de emergência face ao padrão global e essencial de despesas.

    Runway_conforto: liquidez_total / despesa_media_global
    Runway_essencial: liquidez_total / despesa_essencial_mensal
    """
    if despesa_media_global <= 0 or despesa_essencial_mensal <= 0 or liquidez_total < 0:
        return []

    runway_conforto = liquidez_total / despesa_media_global
    runway_essencial = liquidez_total / despesa_essencial_mensal

    conforto_str = _formatar_meses_pt(runway_conforto)
    essencial_str = _formatar_meses_pt(runway_essencial)

    if runway_conforto < _LIMIAR_RUNWAY_CONFORTO_MINIMO or runway_essencial < _LIMIAR_RUNWAY_ESSENCIAL_MINIMO:
        tom = "atencao"
        titulo = "Fundo de emergência abaixo do recomendado"
        descricao = (
            f"A tua liquidez cobre {conforto_str} meses de despesas habituais "
            f"({essencial_str} meses em modo essencial; meta: 6 meses)."
        )
    elif runway_conforto >= _LIMIAR_RUNWAY_CONFORTO_SOLIDO:
        tom = "positivo"
        titulo = "Fundo de emergência sólido"
        descricao = (
            f"A tua liquidez cobre {conforto_str} meses de despesas habituais "
            f"({essencial_str} meses em modo essencial)."
        )
    else:
        tom = "neutro"
        titulo = "Fundo de emergência razoável"
        descricao = (
            f"A tua liquidez cobre {conforto_str} meses de despesas habituais "
            f"({essencial_str} meses em modo essencial)."
        )

    return [
        Insight(
            tipo="runway_emergencia",
            titulo=titulo,
            descricao=descricao,
            tom=tom,
            area="patrimonio",
            valor=f"{conforto_str} m",
        )
    ]


def calcular_sazonalidade_utilities(
    dados: list[tuple[str, Decimal, Decimal | None, Decimal]]
) -> list[Insight]:
    """Deteção de anomalias em faturas de utilities (Eletricidade, Gás, Água, Telecomunicações, etc.)
    comparando preferencialmente com o mesmo mês do ano anterior ou, em fallback, com a média recente.

    `dados`: lista de (nome, valor_atual, valor_homologo, media_recente)
    """
    insights: list[Insight] = []
    for nome, valor_atual, valor_homologo, media_recente in dados:
        if valor_homologo is not None and valor_homologo > 0:
            base = valor_homologo
            origem = "ao ano anterior"
        elif media_recente > 0:
            base = media_recente
            origem = "à média recente"
        else:
            continue

        diferenca = valor_atual - base
        variacao = abs(diferenca) / base

        if variacao <= _LIMIAR_UTILITIES_RELATIVO or abs(diferenca) <= _LIMIAR_UTILITIES_ABSOLUTO:
            continue

        subiu = diferenca > 0
        percentagem = variacao * 100
        sinal = "+" if subiu else "-"
        insights.append(
            Insight(
                tipo=f"sazonalidade_utility:{nome}",
                titulo=f"Fatura de {nome} {'subiu' if subiu else 'desceu'} face {origem}",
                descricao=(
                    f"De {formatar_valor_pt(base)} € para {formatar_valor_pt(valor_atual)} € "
                    f"({sinal}{formatar_valor_pt(abs(diferenca))} € / {sinal}{percentagem:.0f}%)."
                ),
                tom="atencao" if subiu else "positivo",
                area="despesas",
                valor=f"{sinal}{formatar_valor_pt(abs(diferenca))} €",
            )
        )
    return insights


def calcular_racio_custos_fixos(
    *,
    custos_fixos: Decimal,
    rendimento_ordinario: Decimal,
) -> list[Insight]:
    """Acompanhamento da percentagem do rendimento líquido ordinário comprometida com despesas fixas."""
    if rendimento_ordinario <= 0 or custos_fixos < 0:
        return []

    racio = custos_fixos / rendimento_ordinario
    percentagem = racio * 100

    if racio > _LIMIAR_CUSTOS_FIXOS_ALTO:
        tom = "atencao"
        titulo = f"Custos fixos pesam {percentagem:.0f}% do rendimento habitual"
        descricao = "As despesas fixas e inegociáveis ultrapassam o limiar recomendado de 50%."
    elif racio <= _LIMIAR_CUSTOS_FIXOS_BAIXO:
        tom = "positivo"
        titulo = "Excelente flexibilidade financeira"
        descricao = f"Os teus custos fixos consomem apenas {percentagem:.0f}% do teu rendimento ordinário."
    else:
        tom = "neutro"
        titulo = f"Custos fixos pesam {percentagem:.0f}% do rendimento habitual"
        descricao = f"Os teus custos fixos estão dentro de um nível sustentável ({percentagem:.0f}% do rendimento ordinário)."

    return [
        Insight(
            tipo="racio_custos_fixos",
            titulo=titulo,
            descricao=descricao,
            tom=tom,
            area="margem",
            valor=f"{percentagem:.0f}%",
        )
    ]



