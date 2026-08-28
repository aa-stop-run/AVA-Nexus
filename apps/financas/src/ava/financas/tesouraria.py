from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import calendar
from typing import List, Dict, Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class EventoTesouraria:
    data: date
    descricao: str
    valor: Decimal  # Positivo = entrada, Negativo = saída
    categoria: str
    tipo: str  # "salario", "credito", "utilidade", "imposto", "seguro", "consumo"


@dataclass
class PontoProjecao:
    data: date
    saldo_estimado: Decimal
    entradas: Decimal
    saidas: Decimal
    eventos: List[EventoTesouraria]


@dataclass
class ProjecaoTesouraria:
    saldo_atual: Decimal
    saldo_30d: Decimal
    saldo_60d: Decimal
    saldo_90d: Decimal
    ponto_minimo_valor: Decimal
    ponto_minimo_data: date
    margem_seguranca: Decimal
    em_risco_liquidez: bool
    dias_abaixo_margem: int
    pontos_diarios: List[PontoProjecao]
    grandes_compromissos: List[EventoTesouraria]


def data_do_mes(ano: int, mes: int, dia: int) -> date:
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(dia, ultimo_dia))


async def calcular_projecao_tesouraria(
    session: AsyncSession,
    dias_projecao: int = 90,
    margem_seguranca: Decimal = Decimal("500.00"),
    hoje: Optional[date] = None,
) -> ProjecaoTesouraria:
    """Calcula a evolução diária da tesouraria familiar para os próximos N dias."""
    if hoje is None:
        hoje = date.today()

    # 1. Obter saldo líquido atual das contas à ordem
    res_saldo = await session.execute(text("""
        SELECT COALESCE(SUM(s.valor), 0)
        FROM conta c
        LEFT JOIN LATERAL (
            SELECT valor FROM saldo_historico WHERE conta_id = c.id ORDER BY data DESC LIMIT 1
        ) s ON true
        WHERE c.ativo = true AND c.tipo IN ('ordem', 'corrente', 'a_ordem');
    """))
    saldo_inicial = Decimal(str(res_saldo.scalar() or "0.00"))

    # 2. Obter movimentos recorrentes (salários, utilidades, prestações)
    res_rec = await session.execute(text("""
        SELECT r.tipo, r.valor, r.dia_do_mes, r.descricao, c.nome as categoria_nome
        FROM recorrente r
        LEFT JOIN categoria c ON r.categoria_id = c.id
        WHERE r.ativo = true;
    """))
    recorrentes = res_rec.mappings().all()

    # 3. Obter contratos ativos (seguros, telecomunicações, EDP)
    res_contratos = await session.execute(text("""
        SELECT nome, tipo, valor, data_inicio, data_fim, periodicidade
        FROM contrato
        WHERE ativo = true;
    """))
    contratos = res_contratos.mappings().all()

    # 4. Obter veículos para calcular IUC
    res_veiculos = await session.execute(text("""
        SELECT nome, matricula, mes_matricula, ano_matricula, tipo, valor_iuc
        FROM veiculo
        WHERE ativo = true;
    """))
    veiculos = res_veiculos.mappings().all()

    # 5. Média diária de consumo discricionário (supermercado, combustível, etc.)
    res_media = await session.execute(text("""
        SELECT COALESCE(SUM(valor), 0)
        FROM movimento
        WHERE tipo = 'saida'
        AND data >= CURRENT_DATE - INTERVAL '90 days';
    """))
    total_saidas_90d = Decimal(str(res_media.scalar() or "0.00"))
    media_diaria_discricionaria = (total_saidas_90d / Decimal("90")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if media_diaria_discricionaria < Decimal("15.00"):
        media_diaria_discricionaria = Decimal("25.00")  # Média basal familiar por omissão

    # 6. Construção do mapa de eventos diários para o horizonte de projeção
    eventos_por_dia: Dict[date, List[EventoTesouraria]] = {}
    data_fim = hoje + timedelta(days=dias_projecao)

    # Iterar meses no horizonte
    meses_horizonte = []
    curr = date(hoje.year, hoje.month, 1)
    while curr <= data_fim:
        meses_horizonte.append((curr.year, curr.month))
        # Avançar mês
        if curr.month == 12:
            curr = date(curr.year + 1, 1, 1)
        else:
            curr = date(curr.year, curr.month + 1, 1)

    for ano_m, mes_m in meses_horizonte:
        # A. Recorrentes
        for r in recorrentes:
            d_mov = data_do_mes(ano_m, mes_m, r["dia_do_mes"])
            if hoje < d_mov <= data_fim:
                val = Decimal(str(r["valor"]))
                val_sinal = val if r["tipo"] == "entrada" else -val
                cat = r["categoria_nome"] or ("Salário" if r["tipo"] == "entrada" else "Despesa Fixa")
                tipo_evt = "salario" if r["tipo"] == "entrada" else "credito"
                evt = EventoTesouraria(
                    data=d_mov,
                    descricao=r["descricao"] or cat,
                    valor=val_sinal,
                    categoria=cat,
                    tipo=tipo_evt,
                )
                eventos_por_dia.setdefault(d_mov, []).append(evt)

        # B. Contratos Reais (EDP, Seguros, Telecomunicações - excluindo garantias de compras e compras pontuais passadas)
        for c in contratos:
            if not c["valor"]:
                continue

            tipo_c = (c["tipo"] or "").lower()
            nome_c = (c["nome"] or "").lower()
            periodicidade = (c["periodicidade"] or "mensal").lower()

            # Warranties de compras (ex: eletrodomésticos, relógios) NÃO são despesas recorrentes
            if tipo_c == "garantia" or "garantia" in nome_c:
                continue

            dia_deb = c["data_inicio"].day if c["data_inicio"] else 1
            data_debito_mes = data_do_mes(ano_m, mes_m, dia_deb)

            # Verificar periodicidade
            deve_incluir = False
            if periodicidade == "mensal":
                deve_incluir = True
            elif periodicidade in ("unica", "pontual"):
                # Compras pontuais só contam se a data de débito for no futuro e exatamente neste mês
                if c["data_inicio"] and c["data_inicio"] == data_debito_mes and data_debito_mes > hoje:
                    deve_incluir = True
            elif periodicidade == "semestral":
                ref_mes = c["data_inicio"].month if c["data_inicio"] else 1
                if (mes_m - ref_mes) % 6 == 0:
                    deve_incluir = True
            elif periodicidade == "anual":
                ref_mes = c["data_inicio"].month if c["data_inicio"] else 1
                if mes_m == ref_mes:
                    deve_incluir = True

            if deve_incluir and hoje < data_debito_mes <= data_fim:
                val = Decimal(str(c["valor"]))
                evt = EventoTesouraria(
                    data=data_debito_mes,
                    descricao=c["nome"],
                    valor=-val,
                    categoria=c["tipo"] or "Contrato",
                    tipo="utilidade",
                )
                eventos_por_dia.setdefault(data_debito_mes, []).append(evt)

        # C. Impostos Conhecidos em Portugal:
        # IMI: Maio (mês 5) e Novembro (mês 11) ~145 € cada prestação
        if mes_m in (5, 11):
            d_imi = date(ano_m, mes_m, 28)
            if hoje < d_imi <= data_fim:
                evt = EventoTesouraria(
                    data=d_imi,
                    descricao="Pagamento IMI (Autoridade Tributária)",
                    valor=Decimal("-145.00"),
                    categoria="Impostos",
                    tipo="imposto",
                )
                eventos_por_dia.setdefault(d_imi, []).append(evt)

        # D. IUC dos Veículos (mês da matrícula) com valores reais da viatura
        for v in veiculos:
            if v["mes_matricula"] == mes_m:
                val_iuc_num = v.get("valor_iuc")
                if val_iuc_num is None:
                    # Cálculo de fallback pela lei portuguesa se não estiver preenchido
                    if v["tipo"] == "moto":
                        val_iuc_num = Decimal("0.00")
                    elif (v["ano_matricula"] or 2000) < 2007:
                        val_iuc_num = Decimal("36.18")
                    else:
                        val_iuc_num = Decimal("140.00")
                else:
                    val_iuc_num = Decimal(str(val_iuc_num))

                # Se for > 0 (motas 125cc são isentas e não têm débito)
                if val_iuc_num > Decimal("0.00"):
                    d_iuc = date(ano_m, mes_m, 25)
                    if hoje < d_iuc <= data_fim:
                        evt = EventoTesouraria(
                            data=d_iuc,
                            descricao=f"IUC: {v['nome']} ({v['matricula']})",
                            valor=-val_iuc_num,
                            categoria="Veículos",
                            tipo="imposto",
                        )
                        eventos_por_dia.setdefault(d_iuc, []).append(evt)

    # 7. Simulação Dia a Dia
    pontos: List[PontoProjecao] = []
    saldo_corrente = saldo_inicial
    ponto_min = saldo_inicial
    data_min = hoje
    dias_abaixo = 0
    grandes_compromissos: List[EventoTesouraria] = []

    saldo_30d = saldo_inicial
    saldo_60d = saldo_inicial
    saldo_90d = saldo_inicial

    dia_atual = hoje + timedelta(days=1)
    while dia_atual <= data_fim:
        idx = (dia_atual - hoje).days
        evts = eventos_por_dia.get(dia_atual, [])

        ent = Decimal("0.00")
        sai = Decimal("0.00")

        # Deduzir média móvel discricionária diária
        sai += media_diaria_discricionaria

        # Processar eventos pontuais/recorrentes do dia
        for e in evts:
            if e.valor > 0:
                ent += e.valor
            else:
                sai += abs(e.valor)

            # Destacar compromissos relevantes (>= 100 € ou todos os impostos fiscais como IMI e IUC)
            if abs(e.valor) >= Decimal("100.00") or e.tipo == "imposto":
                grandes_compromissos.append(e)

        saldo_corrente = (saldo_corrente + ent - sai).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if saldo_corrente < ponto_min:
            ponto_min = saldo_corrente
            data_min = dia_atual

        if saldo_corrente < margem_seguranca:
            dias_abaixo += 1

        if idx == 30:
            saldo_30d = saldo_corrente
        elif idx == 60:
            saldo_60d = saldo_corrente
        elif idx == 90:
            saldo_90d = saldo_corrente

        pontos.append(PontoProjecao(
            data=dia_atual,
            saldo_estimado=saldo_corrente,
            entradas=ent,
            saidas=sai,
            eventos=evts,
        ))

        dia_atual += timedelta(days=1)

    # Ordenar grandes compromissos por data
    grandes_compromissos.sort(key=lambda x: x.data)

    return ProjecaoTesouraria(
        saldo_atual=saldo_inicial,
        saldo_30d=saldo_30d,
        saldo_60d=saldo_60d,
        saldo_90d=saldo_90d,
        ponto_minimo_valor=ponto_min,
        ponto_minimo_data=data_min,
        margem_seguranca=margem_seguranca,
        em_risco_liquidez=ponto_min < margem_seguranca,
        dias_abaixo_margem=dias_abaixo,
        pontos_diarios=pontos,
        grandes_compromissos=grandes_compromissos,
    )
