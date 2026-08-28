from datetime import datetime


def gerar_daily_briefing(
    dados_consolidados: dict,
    meteo: dict | None = None,
    user_nome: str = "aa-stop-run",
    incluir_saude: bool = True,
) -> dict:
    """Gera um briefing ágil focado na meteorologia, agenda, saúde biométrica e notas imediatas do dia."""
    pontos = []

    # 1. Meteorologia em Tempo Real
    if meteo:
        desc = meteo.get("descricao", "").lower()
        temp = meteo.get("temperatura")
        temp_max = meteo.get("temp_max")
        prob_chuva = meteo.get("prob_chuva", 0)
        alerta_chuva = f" com {prob_chuva}% de probabilidade de chuva" if prob_chuva > 30 else ""
        if temp is not None:
            max_str = f", com máxima de {temp_max}°C" if temp_max is not None else ""
            pontos.append(f"No Grande Porto estão {temp}°C com {desc}{max_str}{alerta_chuva}.")
        else:
            pontos.append("Meteorologia nominal para a região do Porto.")
    else:
        pontos.append("Céu limpo e tempo ameno na região do Porto.")

    # 2. Agenda e Compromissos Familiares
    eventos_hoje = dados_consolidados.get("agenda_eventos_hoje", [])
    total_hoje = dados_consolidados.get("agenda_total_hoje", len(eventos_hoje))
    proximos_eventos = dados_consolidados.get("agenda_eventos", [])

    if total_hoje > 0 and eventos_hoje:
        detalhes = ", ".join(f"às {e.get('hora', '')} ({e.get('titulo', '')})" for e in eventos_hoje[:3])
        pontos.append(f"Hoje tens {total_hoje} compromisso(s) na agenda: {detalhes}.")
    elif proximos_eventos:
        prox = proximos_eventos[0]
        hora_str = f" às {prox['hora']}" if prox.get("hora") else ""
        data_str = prox.get("data", "")
        if len(data_str) == 10 and data_str[4] == "-":
            data_formatada = f"{data_str[8:10]}/{data_str[5:7]}"
        else:
            data_formatada = data_str
        pontos.append(f"A tua agenda para hoje está livre. Próximo compromisso a {data_formatada}{hora_str}: {prox.get('titulo', '')}.")
    else:
        pontos.append("Agenda livre e sem compromissos pendentes para os próximos dias.")

    # 3. Métricas de Saúde e Recuperação (Smartwatch / Galaxy Watch)
    if incluir_saude:
        from hub.services.saude_metrics_service import obter_resumo_saude_para_briefing
        resumo_saude = dados_consolidados.get("saude_resumo") or obter_resumo_saude_para_briefing(titular=user_nome)
        if resumo_saude:
            pontos.append(resumo_saude)

        # Alerta de stock baixo de medicação para o utilizador
        meds_baixo = dados_consolidados.get("medicamentos_stock_baixo", [])
        meds_user = [m for m in meds_baixo if user_nome.lower() in m.get("titular", "").lower()]
        if meds_user:
            nomes_meds = ", ".join(f"{m['nome']} ({m['stock_atual']} un.)" for m in meds_user[:2])
            pontos.append(f"Aviso de farmácia: tens stock baixo de {nomes_meds}. Lembra-te de pedir receita médica.")

    # 4. Saudação Temporal Personalizada
    hora = datetime.now().hour
    if 5 <= hora < 12:
        saudacao = f"Bom dia, {user_nome}!"
    elif 12 <= hora < 20:
        saudacao = f"Boa tarde, {user_nome}!"
    else:
        saudacao = f"Boa noite, {user_nome}!"

    texto_fala = f"{saudacao} Aqui está o teu resumo: " + " ".join(pontos)

    return {
        "saudacao": saudacao,
        "pontos": pontos,
        "texto_fala": texto_fala,
    }
