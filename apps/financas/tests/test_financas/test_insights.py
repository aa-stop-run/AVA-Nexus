import uuid
from decimal import Decimal

from ava.financas.insights import (
    Insight,
    calcular_mensalidade,
    calcular_projecao_poupanca,
    calcular_racio_custos_fixos,
    calcular_recuperacao_ressarcimento,
    calcular_runway_emergencia,
    calcular_sazonalidade_utilities,
    calcular_tendencia_categoria,
    calcular_tendencia_margem,
)
from ava.models.recorrente import Recorrente


def _recorrente(*, valor: str, descricao: str = "Netflix") -> Recorrente:
    return Recorrente(
        id=uuid.uuid4(), tipo="saida", categoria_id=uuid.uuid4(), titular_id=uuid.uuid4(),
        valor=Decimal(valor), dia_do_mes=5, descricao=descricao, ativo=True,
    )


def test_calcular_mensalidade_deteta_subida_acima_do_limiar():
    recorrente = _recorrente(valor="12.99")

    insights = calcular_mensalidade([(recorrente, Decimal("15.99"))])

    assert len(insights) == 1
    assert insights[0].tom == "atencao"
    assert insights[0].area == "despesas"
    assert insights[0].titulo == "A tua mensalidade de Netflix subiu"
    assert insights[0].descricao == "De 12,99 € para 15,99 €"
    assert insights[0].valor == "+3,00 €"
    assert insights[0].tipo == f"mensalidade:{recorrente.id}"


def test_calcular_mensalidade_deteta_descida_acima_do_limiar():
    recorrente = _recorrente(valor="15.99")

    insights = calcular_mensalidade([(recorrente, Decimal("12.99"))])

    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "A tua mensalidade de Netflix desceu"
    assert insights[0].valor == "-3,00 €"


def test_calcular_mensalidade_ignora_variacao_dentro_do_limiar():
    # |13.05 - 12.99| / 12.99 ~= 0,46% -- bem dentro do limiar de 1%.
    recorrente = _recorrente(valor="12.99")

    insights = calcular_mensalidade([(recorrente, Decimal("13.05"))])

    assert insights == []


def test_calcular_mensalidade_ignora_recorrente_sem_movimento_real():
    recorrente = _recorrente(valor="12.99")

    insights = calcular_mensalidade([(recorrente, None)])

    assert insights == []


def test_calcular_mensalidade_processa_varios_pares_independentemente():
    sobe = _recorrente(valor="10.00", descricao="Spotify")
    estavel = _recorrente(valor="20.00", descricao="Renda")

    insights = calcular_mensalidade([
        (sobe, Decimal("12.00")),
        (estavel, Decimal("20.00")),
    ])

    assert len(insights) == 1
    assert insights[0].titulo == "A tua mensalidade de Spotify subiu"


def test_calcular_tendencia_margem_deteta_melhoria():
    # anteriores = [200, 180, 190] -> média 190; atual = 400 -> diferença +210
    margens = [
        Decimal("100"), Decimal("150"), Decimal("200"),
        Decimal("180"), Decimal("190"), Decimal("400"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert len(insights) == 1
    assert insights[0].tipo == "tendencia_margem"
    assert insights[0].area == "margem"
    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "A tua margem estrutural está a melhorar"
    assert insights[0].descricao == "Face à média dos últimos 3 meses."
    assert insights[0].valor == "+210,00 €"
    assert insights[0].serie == tuple(margens)


def test_calcular_tendencia_margem_deteta_piora():
    # anteriores = [500, 500, 500] -> média 500; atual = 100 -> diferença -400
    margens = [
        Decimal("50"), Decimal("80"), Decimal("500"),
        Decimal("500"), Decimal("500"), Decimal("100"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "A tua margem estrutural está a piorar"
    assert insights[0].valor == "-400,00 €"


def test_calcular_tendencia_margem_ignora_variacao_pequena():
    # anteriores = [200, 210, 190] -> média 200; atual = 220 -> diferença +20, dentro do limiar de 50
    margens = [
        Decimal("100"), Decimal("100"), Decimal("200"),
        Decimal("210"), Decimal("190"), Decimal("220"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert insights == []


def test_calcular_tendencia_margem_precisa_de_pelo_menos_4_meses():
    assert calcular_tendencia_margem([Decimal("100"), Decimal("200"), Decimal("300")]) == []
    assert calcular_tendencia_margem([]) == []


def test_calcular_mensalidade_no_limiar_exato_nao_dispara():
    # variacao == _LIMIAR_MENSALIDADE_RELATIVO (1%) exatamente -- o codigo usa <=, por isso fica de fora.
    recorrente = _recorrente(valor="100.00")

    insights = calcular_mensalidade([(recorrente, Decimal("101.00"))])

    assert insights == []


def test_calcular_mensalidade_logo_acima_do_limiar_dispara():
    recorrente = _recorrente(valor="100.00")

    insights = calcular_mensalidade([(recorrente, Decimal("101.01"))])

    assert len(insights) == 1


def test_calcular_mensalidade_recorrente_com_valor_zero_nao_rebenta():
    recorrente = _recorrente(valor="0.00")

    insights = calcular_mensalidade([(recorrente, Decimal("10.00"))])

    assert insights == []


def test_calcular_tendencia_margem_no_limiar_exato_nao_dispara():
    # diferenca == _LIMIAR_MARGEM_ABSOLUTO (50) exatamente -- fica de fora (<=).
    margens = [
        Decimal("100"), Decimal("100"), Decimal("200"),
        Decimal("200"), Decimal("200"), Decimal("250"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert insights == []


def test_calcular_tendencia_margem_logo_acima_do_limiar_dispara():
    margens = [
        Decimal("100"), Decimal("100"), Decimal("200"),
        Decimal("200"), Decimal("200"), Decimal("250.01"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert len(insights) == 1


def test_calcular_tendencia_margem_atravessa_zero():
    # Media anterior negativa, atual positivo -- exatamente o cenario que justifica o limiar
    # absoluto em vez de percentual (uma percentagem nao faz sentido quando a base e negativa).
    margens = [
        Decimal("-50"), Decimal("-80"), Decimal("-100"),
        Decimal("-100"), Decimal("-100"), Decimal("30"),
    ]

    insights = calcular_tendencia_margem(margens)

    assert len(insights) == 1
    assert insights[0].tom == "positivo"


def test_calcular_tendencia_categoria_deteta_subida_acima_do_limiar():
    # anteriores = [500, 500, 500] -> média 500; atual = 620 -> variação +24%
    dados = [("Alimentação", [
        Decimal("500"), Decimal("500"), Decimal("500"),
        Decimal("500"), Decimal("500"), Decimal("620"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert len(insights) == 1
    assert insights[0].tipo == "tendencia_categoria:Alimentação"
    assert insights[0].area == "despesas"
    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "Alimentação subiu 24% este mês"
    assert insights[0].descricao == "620,00 € vs. média de 500,00 €"
    assert insights[0].valor == "+24%"
    assert insights[0].serie == tuple(dados[0][1])


def test_calcular_tendencia_categoria_deteta_descida_acima_do_limiar():
    # anteriores = [100, 100, 100] -> média 100; atual = 50 -> variação -50%
    dados = [("Lazer", [
        Decimal("100"), Decimal("100"), Decimal("100"),
        Decimal("100"), Decimal("100"), Decimal("50"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "Lazer desceu 50% este mês"
    assert insights[0].valor == "-50%"


def test_calcular_tendencia_categoria_ignora_variacao_pequena():
    # anteriores = [200, 200, 200] -> média 200; atual = 220 -> variação +10%, dentro do limiar de 20%
    dados = [("Transportes", [
        Decimal("200"), Decimal("200"), Decimal("200"),
        Decimal("200"), Decimal("200"), Decimal("220"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert insights == []


def test_calcular_tendencia_categoria_no_limiar_exato_nao_dispara():
    # variação == 20% exatamente -- o codigo usa <=, por isso fica de fora.
    dados = [("Alimentação", [
        Decimal("500"), Decimal("500"), Decimal("500"),
        Decimal("500"), Decimal("500"), Decimal("600"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert insights == []


def test_calcular_tendencia_categoria_logo_acima_do_limiar_dispara():
    dados = [("Alimentação", [
        Decimal("500"), Decimal("500"), Decimal("500"),
        Decimal("500"), Decimal("500"), Decimal("600.01"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert len(insights) == 1


def test_calcular_tendencia_categoria_ignora_grupo_sem_base_de_comparacao():
    # média anterior = 0 -- categoria nova este mês, sem tendência nenhuma para medir (fora do
    # âmbito deste insight -- ver docstring).
    dados = [("Saúde", [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("0"), Decimal("0"), Decimal("300"),
    ])]

    insights = calcular_tendencia_categoria(dados)

    assert insights == []


def test_calcular_tendencia_categoria_processa_varios_grupos_independentemente():
    dados = [
        ("Alimentação", [Decimal("500")] * 5 + [Decimal("620")]),
        ("Transportes", [Decimal("200")] * 6),
    ]

    insights = calcular_tendencia_categoria(dados)

    assert len(insights) == 1
    assert insights[0].tipo == "tendencia_categoria:Alimentação"


def test_calcular_tendencia_categoria_precisa_de_pelo_menos_4_meses():
    dados = [("Alimentação", [Decimal("100"), Decimal("200")])]

    assert calcular_tendencia_categoria(dados) == []


def test_calcular_recuperacao_ressarcimento_soma_todos_os_grupos():
    resumos = [
        (Decimal("300.00"), Decimal("200.00")),
        (Decimal("200.00"), Decimal("140.00")),
    ]
    # total despesas = 500, total reembolsos = 340 -> taxa = 68%

    insights = calcular_recuperacao_ressarcimento(resumos)

    assert len(insights) == 1
    assert insights[0].tipo == "recuperacao_ressarcimento"
    assert insights[0].area == "saude"
    assert insights[0].titulo == "Recuperaste 68% das tuas despesas de saúde"
    assert insights[0].descricao == "Nos últimos 90 dias: 340,00 € de 500,00 €"
    assert insights[0].valor == "68%"


def test_calcular_recuperacao_ressarcimento_tom_atencao_abaixo_de_50_por_cento():
    resumos = [(Decimal("500.00"), Decimal("100.00"))]  # taxa = 20%

    insights = calcular_recuperacao_ressarcimento(resumos)

    assert insights[0].tom == "atencao"


def test_calcular_recuperacao_ressarcimento_tom_neutro_a_50_por_cento_ou_mais():
    resumos = [(Decimal("500.00"), Decimal("250.00"))]  # taxa = 50% exatamente

    insights = calcular_recuperacao_ressarcimento(resumos)

    assert insights[0].tom == "neutro"


def test_calcular_recuperacao_ressarcimento_sem_grupos_nao_dispara():
    assert calcular_recuperacao_ressarcimento([]) == []


def test_calcular_recuperacao_ressarcimento_sem_despesas_nao_dispara():
    # Grupos onde só o reembolso já chegou (despesa ainda por ligar) não têm base para uma taxa.
    resumos = [(Decimal("0"), Decimal("50.00"))]

    assert calcular_recuperacao_ressarcimento(resumos) == []


def test_calcular_projecao_poupanca_deteta_tendencia_positiva():
    # últimos 3 meses (só estes contam): [100, 100, 100] -> média 100 -> projeção 600 (6 meses)
    poupancas = [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("100"), Decimal("100"), Decimal("100"),
    ]

    insights = calcular_projecao_poupanca(poupancas)

    assert len(insights) == 1
    assert insights[0].tipo == "projecao_poupanca"
    assert insights[0].area == "margem"
    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "A este ritmo, em 6 meses terás guardado mais 600,00 €"
    assert insights[0].descricao == "Com base na média dos últimos 3 meses (100,00 €/mês)"
    assert insights[0].valor == "+600,00 €"


def test_calcular_projecao_poupanca_deteta_tendencia_negativa():
    poupancas = [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("-100"), Decimal("-100"), Decimal("-100"),
    ]

    insights = calcular_projecao_poupanca(poupancas)

    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "A este ritmo, em 6 meses terás um défice de 600,00 €"
    assert insights[0].valor == "-600,00 €"


def test_calcular_projecao_poupanca_ignora_media_pequena():
    poupancas = [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("10"), Decimal("10"), Decimal("10"),
    ]

    assert calcular_projecao_poupanca(poupancas) == []


def test_calcular_projecao_poupanca_no_limiar_exato_nao_dispara():
    poupancas = [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("50"), Decimal("50"), Decimal("50"),
    ]

    assert calcular_projecao_poupanca(poupancas) == []


def test_calcular_projecao_poupanca_logo_acima_do_limiar_dispara():
    poupancas = [
        Decimal("0"), Decimal("0"), Decimal("0"),
        Decimal("50"), Decimal("50"), Decimal("50.03"),
    ]

    assert len(calcular_projecao_poupanca(poupancas)) == 1


def test_calcular_projecao_poupanca_precisa_de_pelo_menos_3_meses():
    assert calcular_projecao_poupanca([Decimal("100"), Decimal("100")]) == []
    assert calcular_projecao_poupanca([]) == []


def test_calcular_runway_emergencia_alerta_quando_abaixo_do_recomendado():
    # Liquidez = 3.000€, despesa global = 1.500€/mês (runway 2.0m < 3.0m), despesa essencial = 1.000€/mês (runway 3.0m < 6.0m)
    insights = calcular_runway_emergencia(
        liquidez_total=Decimal("3000"),
        despesa_media_global=Decimal("1500"),
        despesa_essencial_mensal=Decimal("1000"),
    )
    assert len(insights) == 1
    assert insights[0].tipo == "runway_emergencia"
    assert insights[0].area == "patrimonio"
    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "Fundo de emergência abaixo do recomendado"
    assert "2,0 meses" in insights[0].descricao
    assert "3,0 meses em modo essencial" in insights[0].descricao
    assert insights[0].valor == "2,0 m"


def test_calcular_runway_emergencia_positivo_quando_solido():
    # Liquidez = 15.000€, despesa global = 2.000€/mês (runway 7.5m >= 6.0m), essencial = 1.200€/mês (runway 12.5m >= 6.0m)
    insights = calcular_runway_emergencia(
        liquidez_total=Decimal("15000"),
        despesa_media_global=Decimal("2000"),
        despesa_essencial_mensal=Decimal("1200"),
    )
    assert len(insights) == 1
    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "Fundo de emergência sólido"
    assert insights[0].valor == "7,5 m"


def test_calcular_runway_emergencia_neutro_entre_limiares():
    # Liquidez = 8.000€, despesa global = 2.000€/mês (runway 4.0m, entre 3.0m e 6.0m), essencial = 1.000€/mês (runway 8.0m >= 6.0m)
    insights = calcular_runway_emergencia(
        liquidez_total=Decimal("8000"),
        despesa_media_global=Decimal("2000"),
        despesa_essencial_mensal=Decimal("1000"),
    )
    assert len(insights) == 1
    assert insights[0].tom == "neutro"
    assert insights[0].titulo == "Fundo de emergência razoável"


def test_calcular_runway_emergencia_sem_despesas_ou_liquidez_negativa_nao_gera_insight():
    assert calcular_runway_emergencia(
        liquidez_total=Decimal("1000"),
        despesa_media_global=Decimal("0"),
        despesa_essencial_mensal=Decimal("0"),
    ) == []
    assert calcular_runway_emergencia(
        liquidez_total=Decimal("-500"),
        despesa_media_global=Decimal("1000"),
        despesa_essencial_mensal=Decimal("800"),
    ) == []


def test_calcular_sazonalidade_utilities_compara_homologo_com_subida():
    # Eletricidade: atual 140€, ano passado 100€ (+40€ / +40%) -> Dispara atencao (>20% e >25€)
    dados = [("Eletricidade", Decimal("140.00"), Decimal("100.00"), Decimal("110.00"))]
    insights = calcular_sazonalidade_utilities(dados)

    assert len(insights) == 1
    assert insights[0].tipo == "sazonalidade_utility:Eletricidade"
    assert insights[0].area == "despesas"
    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "Fatura de Eletricidade subiu face ao ano anterior"
    assert "De 100,00 € para 140,00 € (+40,00 € / +40%)" in insights[0].descricao
    assert insights[0].valor == "+40,00 €"


def test_calcular_sazonalidade_utilities_compara_homologo_com_descida():
    # Gás: atual 40€, ano passado 80€ (-40€ / -50%) -> Dispara positivo
    dados = [("Gás", Decimal("40.00"), Decimal("80.00"), Decimal("70.00"))]
    insights = calcular_sazonalidade_utilities(dados)

    assert len(insights) == 1
    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "Fatura de Gás desceu face ao ano anterior"
    assert insights[0].valor == "-40,00 €"


def test_calcular_sazonalidade_utilities_fallback_para_media_recente_quando_sem_homologo():
    # Água: sem homólogo (None), média recente 30€, atual 60€ (+30€ / +100%) -> Dispara atencao
    dados = [("Água", Decimal("60.00"), None, Decimal("30.00"))]
    insights = calcular_sazonalidade_utilities(dados)

    assert len(insights) == 1
    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "Fatura de Água subiu face à média recente"
    assert "De 30,00 € para 60,00 €" in insights[0].descricao


def test_calcular_sazonalidade_utilities_ignora_variacao_pequena():
    # Variação < 25€ absoluta ou < 20% relativa
    dados = [
        ("Telecomunicações", Decimal("55.00"), Decimal("50.00"), Decimal("50.00")),  # +5€ (< 25€)
        ("Eletricidade", Decimal("220.00"), Decimal("200.00"), Decimal("200.00")),  # +20€ / 10% (< 20% e < 25€)
    ]
    assert calcular_sazonalidade_utilities(dados) == []


def test_calcular_racio_custos_fixos_alerta_quando_acima_de_50_pct():
    # Custos fixos = 1.800€, Rendimento = 3.000€ (60% > 50%) -> atencao
    insights = calcular_racio_custos_fixos(
        custos_fixos=Decimal("1800"),
        rendimento_ordinario=Decimal("3000"),
    )
    assert len(insights) == 1
    assert insights[0].tipo == "racio_custos_fixos"
    assert insights[0].area == "margem"
    assert insights[0].tom == "atencao"
    assert insights[0].titulo == "Custos fixos pesam 60% do rendimento habitual"
    assert "ultrapassam o limiar recomendado de 50%" in insights[0].descricao
    assert insights[0].valor == "60%"


def test_calcular_racio_custos_fixos_positivo_quando_abaixo_de_35_pct():
    # Custos fixos = 900€, Rendimento = 3.000€ (30% <= 35%) -> positivo
    insights = calcular_racio_custos_fixos(
        custos_fixos=Decimal("900"),
        rendimento_ordinario=Decimal("3000"),
    )
    assert len(insights) == 1
    assert insights[0].tom == "positivo"
    assert insights[0].titulo == "Excelente flexibilidade financeira"
    assert insights[0].valor == "30%"


def test_calcular_racio_custos_fixos_neutro_entre_35_e_50_pct():
    # Custos fixos = 1.200€, Rendimento = 3.000€ (40%) -> neutro
    insights = calcular_racio_custos_fixos(
        custos_fixos=Decimal("1200"),
        rendimento_ordinario=Decimal("3000"),
    )
    assert len(insights) == 1
    assert insights[0].tom == "neutro"
    assert insights[0].titulo == "Custos fixos pesam 40% do rendimento habitual"
    assert insights[0].valor == "40%"


def test_calcular_racio_custos_fixos_rendimento_zero_ou_negativo_ignora():
    assert calcular_racio_custos_fixos(custos_fixos=Decimal("1000"), rendimento_ordinario=Decimal("0")) == []
    assert calcular_racio_custos_fixos(custos_fixos=Decimal("1000"), rendimento_ordinario=Decimal("-100")) == []
    assert calcular_racio_custos_fixos(custos_fixos=Decimal("-500"), rendimento_ordinario=Decimal("2000")) == []



