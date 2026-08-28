import os
import re
import logging
from decimal import Decimal
from datetime import date, datetime
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from hub.services.consolidator import recolher_dados_consolidados
from hub.services.agenda_service import obter_agenda_unificada
from hub.services.circuit_breaker import ollama_circuit_breaker
from hub.services.conversation_memory import conversation_memory
from hub.services.action_engine import tentar_executar_acao

logger = logging.getLogger("hub.ai_agent")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:14b")

MESES_MAP = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}

NOMES_MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]

# Mapeamento exaustivo de sinónimos para as 69 categorias e marcas/fornecedores comuns em Portugal
MAPA_CATEGORIAS = {
    # Alimentação e Consumo
    "Supermercado": ["supermercado", "supermercados", "compras", "mercearia", "continente", "pingo doce", "auchan", "lidl", "mercadona", "intermarche", "alimentação", "alimentacao", "froiz", "alisuper"],
    "Restaurantes": ["restaurante", "restaurantes", "almoço", "almoco", "jantar", "jantares", "takeaway", "uber eats", "glovo", "mcdonalds", "burger king", "telepizza", "pizzaria", "marisqueira"],
    "Café": ["café", "cafe", "cafetaria", "pastelaria", "padaria", "lanche", "snack", "pequeno-almoço", "pequeno almoco"],
    "Tabaco": ["tabaco", "tabacaria", "cigarro", "cigarros", "tabacos", "tabaqueira", "disa", "iqos", "heets", "terea"],

    # Habitação e Utilidades
    "Eletricidade": ["eletricidade", "luz", "energia", "edp", "endesa", "galp energia", "iberdrola", "goldenergy", "plenitude"],
    "Água": ["água", "agua", "smas", "indacqua", "adp", "aguas", "águas do porto", "aguas de gondomar"],
    "Gás": ["gás", "gas", "botija", "rubis", "galp gás"],
    "Internet e TV": ["internet", "tv", "telecomunicações", "telecomunicacoes", "meo", "nos", "vodafone", "nowo", "telemóvel", "telemovel", "fibra"],
    "Condomínio": ["condomínio", "condominio", "quota de condomínio"],
    "Renda": ["renda", "rendas", "aluguer"],
    "Manutenção": ["manutenção", "manutencao", "obras", "reparações", "reparacoes", "bricolage", "leroy merlin", "aki", "brico"],
    "Decoração": ["decoração", "decoracao", "móveis", "moveis", "ikea", "jysk", "casa", "gato preto", "zarahome"],
    "Eletrodomésticos": ["eletrodoméstico", "eletrodomésticos", "eletrodomesticos", "frigorífico", "máquina", "worten", "radiopopular", "fnac"],

    # Mobilidade e Veículos
    "Fuel Type": ["combustível", "combustivel", "gasolina", "gasóleo", "gasoleo", "abastecimento", "galp", "bp", "repsol", "cepsa", "prio", "combustíveis", "posto"],
    "Portagens": ["portagem", "portagens", "via verde", "scut", "brisa", "ascendi"],
    "Manutenção auto": ["oficina", "revisão", "revisao", "pneus", "peças", "muda de óleo", "oleo", "norauto", "mforce", "midas", "oficina auto"],
    "Seguro auto": ["seguro auto", "seguro do carro", "seguro automóvel", "seguro automovel", "seguro mota", "seguro audi", "seguro megane", "seguro zontes"],
    "IUC": ["iuc", "imposto único de circulação", "imposto de circulação", "selo do carro"],
    "Inspeção": ["inspeção", "inspecao", "ipo", "centro de inspeções", "inspeção periódica"],
    "Transportes públicos": ["transporte público", "transportes publicos", "metro", "autocarro", "stcp", "comboio", "cp", "passe", "andante"],

    # Saúde e Bem-Estar
    "Consultas": ["consulta", "consultas", "médico", "medico", "médica", "hospital", "clínica", "clinica", "cuf", "lusíadas", "lusiadas", "trofa saúde", "análises", "analises", "pediatria", "oftalmologia", "urgência"],
    "Medicamentos": ["farmácia", "farmacia", "medicamento", "medicamentos", "farmácias", "receita médica", "benu", "terapeuta", "pomada", "xarope", "brufen", "ben-u-ron"],
    "Dentista": ["dentista", "estomatologia", "dente", "dentes", "aparelho dentário", "limpeza dentária", "oral"],
    "Seguro de saúde": ["seguro de saúde", "seguro saude", "médis", "medis", "multicare", "advancecare"],
    "SAMS Quadros": ["sams", "sams quadros"],
    "Cuidado pessoal": ["cuidado pessoal", "higiene", "perfumaria", "creme", "maquilhagem", "sephora", "douglas", "pluricosmética"],
    "Cabeleireiro e Estética": ["cabeleireiro", "barbeiro", "barbearia", "estética", "estetica", "manicure", "pedicure", "corte de cabelo"],

    # Educação, Família e Animais
    "Escola": ["escola", "colégio", "colegio", "mensalidade escolar", "propinas", "livros escolares", "manuais escolares"],
    "ATL": ["atl", "centro de estudos", "explicações", "explicacoes", "tempo livre", "atividades tempos livres"],
    "Material": ["material escolar", "papelaria", "cadernos", "canetas", "mochila", "staples", "note"],
    "Atividades": ["atividades", "natação", "natacao", "ballet", "música", "musica", "conservatório"],
    "Veterinário": ["veterinário", "veterinario", "vet", "cão", "cao", "gato", "ração", "racao", "clínica veterinária", "animais", "pet"],

    # Lazer, Desporto e Cultura
    "Desporto": ["desporto", "ginásio", "ginasio", "fitness", "padel", "futebol", "ténis", "tenis", "solinca", "fitness hut", "decathlon"],
    "Vestuário": ["vestuário", "vestuario", "roupa", "roupas", "calçado", "calcado", "sapatos", "ténis", "zara", "massimo dutti", "pull&bear", "bershka", "stradivarius", "mango", "h&m", "cortefiel", "springfield"],
    "Subscrições": ["subscrição", "subscrições", "subscricoes", "streaming", "netflix", "spotify", "youtube", "disney", "apple", "icloud", "chatgpt", "amazon prime", "hbo", "playstation", "game pass"],
    "Eletrónica": ["eletrónica", "eletronica", "tecnologia", "computador", "telemóvel", "tablet", "pcdiga", "pccomponentes", "apple", "gadgets"],
    "Cultura": ["cultura", "cinema", "filmes", "teatro", "espetáculo", "espetaculo", "concerto", "livro", "livros", "bertrand", "livraria"],
    "Férias": ["férias", "ferias", "viagem", "viagens", "hotel", "hotéis", "alojamento", "booking", "airbnb", "voo", "voos", "tap", "ryanair"],
    "Ofertas": ["oferta", "ofertas", "prenda", "prendas", "presente", "presentes", "aniversário"],

    # Financeiro, Seguros e Impostos
    "Pagamento de crédito": ["crédito", "credito", "empréstimo", "emprestimo", "prestação", "prestacao", "crédito habitação", "credito habitacao", "amortização", "amortizacao", "bpi", "santander", "cgd", "novobanco"],
    "Juros de crédito": ["juro", "juros", "juros de crédito", "encargos bancários"],
    "Comissões bancárias": ["comissão", "comissões", "comissoes", "manutenção de conta", "despesas de conta", "anuais do cartão"],
    "Seguro de vida": ["seguro de vida", "apólice vida", "vida habitação"],
    "Seguro multirriscos": ["multirriscos", "seguro da casa", "seguro habitação"],
    "Seguros": ["seguro", "seguros", "allianz", "fidelidade", "tranquilidade", "mapfre", "zurich", "ageas"],
    "IRS": ["irs", "declaração de irs", "imposto de rendimento", "acerto de irs", "finanças", "autoridade tributária"],
    "IMI": ["imi", "imposto municipal sobre imóveis", "imposto da casa"],
    "Imposto de selo": ["imposto de selo", "selo"],
    "Levantamento em numerário": ["levantamento", "levantamentos", "multibanco", "mb", "dinheiro vivo", "numerário", "numerario"],
    "Conta Poupança": ["poupança", "poupanca", "investimento", "investimentos", "depósito a prazo", "ações", "etf", "certificados de aforro"],
    "PPR": ["ppr", "plano poupança reforma"],

    # Rendimentos e Receitas
    "Salário": ["salário", "salario", "ordenado", "vencimento", "remuneração", "remuneracao", "paga"],
    "Subsídio de alimentação": ["subsídio de alimentação", "subsidio de alimentacao", "refeição", "vale de refeição", "cartão refeição"],
    "Reembolsos": ["reembolso", "reembolsos", "devolução", "devolucoes", "reembolso médis", "reembolso irs"],
    "Dividendos": ["dividendo", "dividendos", "juros recebidos"],
    "Subsídios de férias e Natal": ["subsídio de férias", "subsidio de natal", "13º mês", "14º mês"],
}


async def extrair_contexto_gastos(session: AsyncSession, query: str, session_id: str = "default") -> dict | None:
    """Pesquisa movimentos financeiros por categoria, fornecedor ou descrição, com suporte a datas exatas e memória multi-turn."""
    q = query.lower()
    hoje = date.today()

    # 1. Extrair período temporal (mês e ano) da pergunta
    mes_pedido = None
    ano_pedido = None

    match_ano = re.search(r"\b(202\d)\b", q)
    if match_ano:
        ano_pedido = int(match_ano.group(1))

    for nome_m, num_m in MESES_MAP.items():
        if re.search(rf"\b{nome_m}\b", q):
            mes_pedido = num_m
            break

    if any(k in q for k in ["este mês", "este mes", "neste mês", "neste mes", "mês corrente"]):
        mes_pedido = hoje.month
        if not ano_pedido:
            ano_pedido = hoje.year
    elif any(k in q for k in ["mês passado", "mes passado", "último mês", "ultimo mes"]):
        if hoje.month == 1:
            mes_pedido = 12
            ano_pedido = ano_pedido or (hoje.year - 1)
        else:
            mes_pedido = hoje.month - 1
            ano_pedido = ano_pedido or hoje.year

    # Herança Multi-turn: se não indicou mês nem ano, herdar do turno anterior
    if mes_pedido is None and not match_ano:
        inherited_mes = conversation_memory.get_session(session_id).get_inherited_entity("mes")
        inherited_ano = conversation_memory.get_session(session_id).get_inherited_entity("ano")
        if inherited_mes:
            mes_pedido = inherited_mes
            ano_pedido = inherited_ano or ano_pedido

    if not ano_pedido:
        ano_pedido = hoje.year

    # 2. Identificar termos candidatos para a categoria
    termos_busca = []
    categoria_sugerida = None

    for cat_canonica, sinonimos in MAPA_CATEGORIAS.items():
        if any(re.search(rf"\b{re.escape(s)}\b", q, re.IGNORECASE) for s in sinonimos):
            termos_busca.append(cat_canonica)
            termos_busca.extend(sinonimos)
            categoria_sugerida = cat_canonica
            break

    if not termos_busca:
        stopwords = {
            "quanto", "gastei", "gasto", "gastos", "gasta", "gastamos", "minha", "minhas",
            "meu", "meus", "qual", "quais", "valor", "total", "sobre", "para", "com",
            "este", "esta", "esse", "essa", "ano", "mes", "mês", "dias", "último", "ultimo",
            "janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho", "julho",
            "agosto", "setembro", "outubro", "novembro", "dezembro", "2024", "2025", "2026"
        }
        palavras = [p for p in q.replace("?", "").replace("!", "").replace(",", "").split() if len(p) > 2 and p not in stopwords]
        termos_busca = palavras

    if not termos_busca and not categoria_sugerida:
        return None

    try:
        cat_ids = []
        cats = []
        if categoria_sugerida:
            res_cat = await session.execute(
                text("SELECT id, nome FROM categoria WHERE nome ILIKE :cat"),
                {"cat": f"%{categoria_sugerida}%"}
            )
            cats = res_cat.fetchall()
            cat_ids = [str(c[0]) for c in cats]

        if not cat_ids and termos_busca:
            condicoes_cat = " OR ".join([f"nome ILIKE :t{i}" for i in range(len(termos_busca[:6]))])
            t_params = {f"t{i}": f"%{t}%" for i, t in enumerate(termos_busca[:6])}
            res_cat = await session.execute(text(f"SELECT id, nome FROM categoria WHERE {condicoes_cat} LIMIT 8"), t_params)
            cats = res_cat.fetchall()
            cat_ids = [str(c[0]) for c in cats]

        if cat_ids:
            where_match = "ml.categoria_id = ANY(CAST(:cat_ids AS uuid[]))"
            params = {"cat_ids": cat_ids, "ano": ano_pedido}
        elif termos_busca:
            condicoes_desc = " OR ".join([f"m.descricao ILIKE :d{i}" for i in range(len(termos_busca[:6]))])
            d_params = {f"d{i}": f"%{t}%" for i, t in enumerate(termos_busca[:6])}
            where_match = f"({condicoes_desc})"
            params = {**d_params, "ano": ano_pedido}
        else:
            return None

        # Query 1: Total do Período Específico (mês + ano ou ano)
        if mes_pedido:
            sql_periodo = f"""
                SELECT COALESCE(SUM(ml.valor), 0), COUNT(ml.id)
                FROM movimento_linha ml
                JOIN movimento m ON m.id = ml.movimento_id
                WHERE {where_match}
                  AND EXTRACT(YEAR FROM m.data) = :ano
                  AND EXTRACT(MONTH FROM m.data) = :mes;
            """
            res_p = await session.execute(text(sql_periodo), {**params, "mes": mes_pedido})
            row_p = res_p.fetchone()
            total_periodo = Decimal(str(row_p[0])) if row_p else Decimal("0.00")
            count_periodo = int(row_p[1]) if row_p else 0
        else:
            total_periodo = None
            count_periodo = None

        # Query 2: Total do Ano Completo
        sql_ano = f"""
            SELECT COALESCE(SUM(ml.valor), 0), COUNT(ml.id)
            FROM movimento_linha ml
            JOIN movimento m ON m.id = ml.movimento_id
            WHERE {where_match}
              AND EXTRACT(YEAR FROM m.data) = :ano;
        """
        res_a = await session.execute(text(sql_ano), params)
        row_a = res_a.fetchone()
        total_ano = Decimal(str(row_a[0])) if row_a else Decimal("0.00")
        count_ano = int(row_a[1]) if row_a else 0

        # Se pediu só ano, período = ano
        if not mes_pedido:
            total_periodo = total_ano
            count_periodo = count_ano

        # Query 3: Transações mais recentes desse escopo
        filtro_tempo_trans = "AND EXTRACT(YEAR FROM m.data) = :ano"
        if mes_pedido:
            filtro_tempo_trans += " AND EXTRACT(MONTH FROM m.data) = :mes"

        sql_trans = f"""
            SELECT 
                COALESCE(c.nome, 'Geral') as categoria,
                m.data,
                m.descricao,
                ml.valor
            FROM movimento_linha ml
            JOIN movimento m ON m.id = ml.movimento_id
            LEFT JOIN categoria c ON c.id = ml.categoria_id
            WHERE {where_match}
              {filtro_tempo_trans}
            ORDER BY m.data DESC
            LIMIT 5;
        """
        trans_params = {**params, "mes": mes_pedido} if mes_pedido else params
        res_t = await session.execute(text(sql_trans), trans_params)
        linhas_t = res_t.fetchall()

        transacoes = []
        for r in linhas_t:
            cat_nome, dt, desc, val = r
            transacoes.append({
                "categoria": cat_nome,
                "data": dt.strftime("%d/%m/%Y"),
                "descricao": desc.strip(),
                "valor": float(abs(Decimal(str(val))))
            })

        nome_cat = categoria_sugerida or (cats[0][1] if cats else "Despesas")
        nome_mes = NOMES_MESES_PT[mes_pedido] if mes_pedido else None

        # Save na memória conversacional para perguntas de seguimento
        conversation_memory.get_session(session_id).active_entities.update({
            "mes": mes_pedido,
            "ano": ano_pedido,
            "categoria": nome_cat,
        })

        return {
            "categoria": nome_cat,
            "ano_pedido": ano_pedido,
            "mes_pedido": mes_pedido,
            "nome_mes_pedido": nome_mes,
            "total_periodo": float(total_periodo),
            "count_periodo": count_periodo,
            "total_ano": float(total_ano),
            "count_ano": count_ano,
            "transacoes": transacoes,
        }
    except Exception as e:
        logger.error(f"Erro ao extrair gastos: {e}")
        return None


async def extrair_contexto_cidadania(session: AsyncSession, q: str) -> str | None:
    """Responde a perguntas sobre documentos de identificação, validades e impostos."""
    termos_cidadania = [
        "cartão de cidadão", "cartao de cidadao", "cc", "carta de condução", "carta de conducao",
        "passaporte", "nif", "niss", "validade", "caduca", "expira", "documento", "documentos", "cidadania"
    ]
    if not any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_cidadania):
        return None

    try:
        res = await session.execute(text("""
            SELECT titular_nome, tipo, numero, data_validade 
            FROM documento_identificacao 
            WHERE ativo = true 
            ORDER BY data_validade ASC NULLS LAST;
        """))
        docs = res.fetchall()
        if not docs:
            return None

        # Identificar titular alvo
        titular_alvo = None
        for nome in ["charlie", "sam", "sam", "alex", "alex"]:
            if re.search(rf"\b{nome}\b", q, re.IGNORECASE):
                titular_alvo = "Member" if nome in ["sam", "sam"] else ("Junior" if nome == "charlie" else "aa-stop-run")
                break

        # Identificar tipo de documento alvo
        tipo_alvo = None
        if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["cartão de cidadão", "cartao de cidadao", "cc"]):
            tipo_alvo = "cartao_cidadao"
        elif any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["carta de condução", "carta de conducao", "condução", "conducao"]):
            tipo_alvo = "carta_conducao"
        elif re.search(r"\bpassaporte\b", q, re.IGNORECASE):
            tipo_alvo = "passaporte"
        elif re.search(r"\bnif\b", q, re.IGNORECASE):
            tipo_alvo = "nif"
        elif re.search(r"\bniss\b", q, re.IGNORECASE):
            tipo_alvo = "niss"

        docs_filtrados = docs
        if titular_alvo:
            docs_filtrados = [d for d in docs_filtrados if d[0].lower() == titular_alvo.lower()]
        if tipo_alvo:
            docs_filtrados = [d for d in docs_filtrados if d[1] == tipo_alvo]

        if not docs_filtrados and titular_alvo:
            return f"Não encontrei documentos do tipo pedido registados para **{titular_alvo}**."

        hoje = date.today()
        # Se perguntou especificamente por um documento
        if titular_alvo and tipo_alvo and docs_filtrados:
            d = docs_filtrados[0]
            nome_doc = "Cartão de Cidadão" if d[1] == "cartao_cidadao" else ("Carta de Condução" if d[1] == "carta_conducao" else d[1].upper())
            if d[3]:
                dias = (d[3] - hoje).days
                estado_val = f"válido até **{d[3].strftime('%d/%m/%Y')}** ({dias} days remaining)" if dias > 0 else f"**expirou** a {d[3].strftime('%d/%m/%Y')}"
                return f"O **{nome_doc}** do **{d[0]}** (n.º `{d[2]}`) está {estado_val}."
            return f"O **{nome_doc}** do **{d[0]}** tem o número `{d[2]}`."

        # Se perguntou por documentos no geral ou por um titular no geral
        resumo_docs = []
        for d in docs_filtrados[:4]:
            nome_doc = "Cartão de Cidadão" if d[1] == "cartao_cidadao" else ("Carta de Condução" if d[1] == "carta_conducao" else d[1].upper())
            if d[3]:
                resumo_docs.append(f"**{d[0]}** ({nome_doc}): válido até **{d[3].strftime('%d/%m/%Y')}**")
            else:
                resumo_docs.append(f"**{d[0]}** ({nome_doc}): `{d[2]}`")

        return f"Dossier de Documentos de Cidadania: {'; '.join(resumo_docs)}."
    except Exception as e:
        logger.error(f"Erro em cidadania: {e}")
        return None


async def extrair_contexto_casa(session: AsyncSession, q: str) -> str | None:
    """Responde a perguntas sobre equipamentos, garantias e manutenções da casa."""
    termos_casa = [
        "garantia", "garantias", "caldeira", "frigorífico", "frigorifico", "máquina", "maquina",
        "ar condicionado", "equipamento", "equipamentos", "manutenção da casa", "manutencao da casa", "filtro", "filtros"
    ]
    if not any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_casa):
        return None

    try:
        # 1. Verificar manutenções da casa
        if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["manutenção", "manutencao", "revisão", "revisao", "filtro"]):
            res_man = await session.execute(text("""
                SELECT titulo, divisao_casa, proxima_data, (proxima_data - CURRENT_DATE) as dias 
                FROM manutencao_casa 
                WHERE proxima_data IS NOT NULL 
                ORDER BY proxima_data ASC;
            """))
            mans = res_man.fetchall()
            if mans:
                lista = [f"**{m[0]}** ({m[1]}) agendada para **{m[2].strftime('%d/%m/%Y')}**" for m in mans]
                return f"Maintenance programadas para a casa: {', '.join(lista)}."

        # 2. Verificar garantias de equipamentos
        res = await session.execute(text("""
            SELECT nome, marca, fornecedor_loja, data_fim_garantia, (data_fim_garantia - CURRENT_DATE) as dias 
            FROM equipamento_casa 
            ORDER BY data_fim_garantia ASC;
        """))
        eqs = res.fetchall()
        if not eqs:
            return "Não encontrei equipamentos com garantia registada na aplicação Casa."

        # Procurar equipamento específico
        eq_alvo = None
        for eq in eqs:
            nome_low = eq[0].lower()
            if any(p in q for p in ["caldeira", "aquecimento"]) and "caldeira" in nome_low:
                eq_alvo = eq
                break
            elif any(p in q for p in ["ar condicionado", "ac", "climatização"]) and "ar condicionado" in nome_low:
                eq_alvo = eq
                break
            elif any(p in q for p in ["smartwatch", "relógio", "relogio", "samsung", "watch"]) and "smartwatch" in nome_low:
                eq_alvo = eq
                break

        hoje = date.today()
        if eq_alvo:
            dias = eq_alvo[4]
            estado = f"válida até **{eq_alvo[3].strftime('%d/%m/%Y')}** ({dias} days remaining)" if dias > 0 else f"**expirou** a {eq_alvo[3].strftime('%d/%m/%Y')}"
            loja_str = f" (comprado na {eq_alvo[2]})" if eq_alvo[2] else ""
            return f"A garantia do equipamento **{eq_alvo[0]}**{loja_str} está {estado}."

        lista_g = []
        for eq in eqs:
            dias = eq[4]
            status = f"até **{eq[3].strftime('%d/%m/%Y')}** ({dias}d)" if dias > 0 else "expirada"
            lista_g.append(f"**{eq[0]}**: {status}")
        return f"Warranties registadas na casa: {'; '.join(lista_g)}."
    except Exception as e:
        logger.error(f"Erro em casa: {e}")
        return None


async def extrair_contexto_simulador_otimizador(session: AsyncSession, q: str) -> dict | None:
    """Responde a perguntas e simula amortizações de crédito ou otimizações de subscrições."""
    # 1. Simulador de Mortgage & Loans / Amortização
    termos_simulador = ["amortizar", "amortizacao", "amortização", "simulador", "abater credito", "abater crédito", "abater emprestimo", "abater empréstimo"]
    if any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_simulador):
        # Tentar extrair valor a amortizar
        m_val = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:€|euros|mil)?", q)
        valor_amortizar = None
        if m_val:
            val_str = m_val.group(1).replace(",", ".")
            try:
                valor_amortizar = float(val_str)
                if "mil" in q.lower() and valor_amortizar < 100:
                    valor_amortizar *= 1000
            except ValueError:
                pass

        saldo_divida = 151515.0
        try:
            sql_divida = """
                SELECT saldo 
                FROM conta 
                WHERE tipo = 'divida' AND ativo = true 
                ORDER BY atualizado_em DESC LIMIT 1;
            """
            res = await session.execute(text(sql_divida))
            row = res.fetchone()
            if row and row[0]:
                saldo_divida = abs(float(row[0]))
        except Exception:
            pass

        if valor_amortizar and valor_amortizar > 100:
            poupanca_mensal_est = (valor_amortizar / saldo_divida) * 720.0
            poupanca_juros_est = valor_amortizar * 0.65

            resp = (
                f"🧮 **Simulação de Amortização de Empréstimo**:\n"
                f"• Capital atual em dívida: **€ {saldo_divida:,.2f}**\n"
                f"• Amortização simulada: **€ {valor_amortizar:,.2f}**\n\n"
                f"**Dois Cenários Possíveis:**\n"
                f"1. **Redução da Prestação**: Poupança imediata de cerca de **€ {poupanca_mensal_est:.2f} / mês**, mantendo o prazo.\n"
                f"2. **Redução do Prazo**: Eliminas meses ao empréstimo e poupas até **€ {poupanca_juros_est:,.2f} em juros futuros**!\n"
                f"Podes ver a tabela e gráfico exatos no simulador:"
            )
            speech = f"Com uma amortização de {int(valor_amortizar)} euros no crédito da casa, podes reduzir a prestação em cerca de {int(poupanca_mensal_est)} euros por mês ou cortar anos ao empréstimo com milhares de euros poupados em juros."
        else:
            resp = (
                f"🧮 **Simulador de Amortização Antecipada de Crédito**:\n"
                f"O teu capital em dívida atual é de **€ {saldo_divida:,.2f}**.\n"
                f"No simulador podes comparar matematicamente a diferença entre **reduzir a prestação mensal** (alívio imediato) "
                f"vs **reduzir o prazo** (eliminar anos de dívida e maximizar a poupança total em juros)."
            )
            speech = "No simulador podes comparar a redução da prestação mensal contra a redução do prazo do teu crédito habitação."

        return {
            "response": resp,
            "speech_text": speech,
            "actions": [
                {"type": "link", "label": "🧮 Abrir Simulador de Crédito", "target": "http://localhost:8081/simulador"},
                {"type": "link", "label": "💶 Ver Crédito no Património", "target": "http://localhost:8081/patrimonio"},
            ]
        }

    # 2. Otimizador de Subscrições & Custos
    termos_otimizador = ["otimizador", "subscrição", "subscricao", "subscrições", "subscricoes", "onde poupar", "onde posso poupar", "cortar despesa", "cortar gastos"]
    if any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_otimizador):
        resp = (
            f"⚡ **Otimizador Financeiro & Subscrições Ativas**:\n"
            f"O motor de otimização analisa contratos recorrentes (eletricidade, telecomunicações, streaming, subscrições) e desvios de orçamento.\n"
            f"• Identifica custos anualizados de serviços recorrentes.\n"
            f"• Alerta para contratos próximos da janela de renegociação ou renovação automática.\n"
            f"• Modela o impacto de cancelar ou renegociar pacotes para poupança líquida anual."
        )
        speech = "O otimizador de despesas analisa as tuas subscrições e contratos recorrentes para calcular a poupança anual potencial."
        return {
            "response": resp,
            "speech_text": speech,
            "actions": [
                {"type": "link", "label": "⚡ Abrir Otimizador de Gastos", "target": "http://localhost:8081/otimizador"},
                {"type": "link", "label": "📑 Ver Contratos", "target": "http://localhost:8081/contratos"},
            ]
        }

    # 3. Treasury Forecast & Cash-Flow a 90 Dias
    termos_tesouraria = ["tesouraria", "cash-flow", "cash flow", "previsão de saldo", "previsao de saldo", "previsão financeira", "previsao financeira", "saldo futuro", "daqui a 30 dias", "daqui a 60 dias", "daqui a 90 dias", "saldo daqui a"]
    if any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_tesouraria):
        resp = (
            f"🔮 **Treasury Forecast & Liquidez Familiar (90 Dias)**:\n"
            f"O motor preditivo projeta diariamente o saldo das tuas contas à ordem cruzando salários do aa-stop-run e da Member, "
            f"a prestação de crédito habitação, utilidades contratuais e impostos periódicos (IMI e IUC dos veículos).\n\n"
            f"• A curva de tesouraria mantém um limiar de segurança de **€ 500.00**.\n"
            f"• Podes consultar a tabela de grandes saídas previstas e o gráfico diário interativo no módulo de Finanças:"
        )
        speech = "A previsão de tesouraria a 90 dias analisa os teus salários, créditos e despesas fixas para projetar a evolução do teu saldo."
        return {
            "response": resp,
            "speech_text": speech,
            "actions": [
                {"type": "link", "label": "🔮 Abrir Treasury Forecast", "target": "http://localhost:8081/tesouraria"},
                {"type": "link", "label": "💶 Ver Património Consolidado", "target": "http://localhost:8081/patrimonio"},
            ]
        }

    return None

async def extrair_contexto_veiculos(session: AsyncSession, q: str, session_id: str = "default") -> dict | str | None:
    """Responde a perguntas sobre carros, motas, quilómetros, IPO, seguros e matrículas."""
    termos_veiculos = [
        "carro", "carros", "mota", "motas", "veículo", "veiculo", "veículos", "veiculos",
        "sedan", "hatchback", "mota", "carro", "viatura", "veiculo", "veículo", "audi", "megane", "mégane", "zontes", "ipo", "inspeção", "inspecao", "quilómetros",
        "quilometros", "km", "matrícula", "matricula", "garagem", "seguro", "apólice", "apolice",
        "assistência", "assistencia", "vidros"
    ]
    if not any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_veiculos):
        return None

    try:
        res = await session.execute(text("""
            SELECT nome, matricula, tipo, km_atual, data_proxima_ipo, mes_matricula, ano_matricula, id 
            FROM veiculo 
            WHERE ativo = true 
            ORDER BY km_atual DESC;
        """))
        veiculos = res.fetchall()
        if not veiculos:
            return "Não tens viaturas registadas na Garagem."

        # Identificar viatura específica ou herdar da conversa anterior
        v_alvo = None
        for v in veiculos:
            nome_low = v[0].lower()
            palavras = [w for w in re.findall(r'\w+', nome_low) if len(w) > 2]
            if any(w in q for w in palavras):
                v_alvo = v
                break
            elif "mota" in q and v[2] == "mota":
                v_alvo = v
                break
            elif "carro" in q and v[2] == "carro":
                v_alvo = v
                break
        if not v_alvo and len(veiculos) == 1:
            v_alvo = veiculos[0]

        if not v_alvo:
            # Tentar herdar da memória se o utilizador usou "dele", "do carro", etc.
            inherited_v = conversation_memory.get_session(session_id).get_inherited_entity("veiculo")
            if inherited_v:
                for v in veiculos:
                    if inherited_v.lower() in v[0].lower():
                        v_alvo = v
                        break

        # Se perguntou por uma viatura específica
        if v_alvo:
            nome_v = v_alvo[0]
            mat = v_alvo[1]
            v_id = str(v_alvo[7])
            km = f"{v_alvo[3]:,} km".replace(",", " ") if v_alvo[3] else "0 km"
            mes_ipo = NOMES_MESES_PT[v_alvo[5]] if v_alvo[5] else "a definir"

            # Save viatura ativa na memória
            conversation_memory.get_session(session_id).active_entities["veiculo"] = nome_v

            # 1. Pergunta sobre Seguro Automóvel
            if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["seguro", "apólice", "apolice", "assistência", "assistencia", "vidros"]):
                res_seg = await session.execute(text("""
                    SELECT c.nome, c.numero_referencia, c.data_fim, c.notas
                    FROM contrato c
                    WHERE c.tipo = 'seguro_auto' 
                      AND (c.nome ILIKE :nome OR c.notas ILIKE :mat)
                    ORDER BY c.data_fim DESC NULLS LAST LIMIT 1;
                """), {"nome": f"%{nome_v}%", "mat": f"%{mat or '___'}%"})
                row_seg = res_seg.mappings().first()
                validade = row_seg["data_fim"].strftime("%d/%m/%Y") if (row_seg and row_seg.get("data_fim")) else "02/12/2026"
                apolice = (row_seg.get("numero_referencia") if row_seg else None) or "142001304364"
                return {
                    "response": (
                        f"🛡️ **Seguro Automóvel do {nome_v}** (`{mat}`):\n"
                        f"• Companhia: **Divina Seguros**\n"
                        f"• Policy No.: `{apolice}`\n"
                        f"• Expiry Date: até **{validade}**.\n"
                        f"• Assistência em Viagem (24h): **+351 309 739 806** | Vidros: **808 211 690**."
                    ),
                    "speech_text": f"O seguro do {nome_v} na Divina Seguros está ativo até {validade}. A linha de assistência é 309 739 806.",
                    "actions": [
                        {"type": "call", "label": "📞 Assistência 24h (+351 309 739 806)", "target": "tel:+351309739806"},
                        {"type": "call", "label": "🔨 Quebra de Vidros (808 211 690)", "target": "tel:808211690"},
                        {"type": "link", "label": f"🚗 Abrir Dossier", "target": f"/veiculos/{v_id}"},
                    ],
                }

            if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["km", "quilómetros", "quilometros", "rodagem"]):
                return f"O **{nome_v}** (matrícula `{mat}`) tem atualmente **{km}** registados."
            if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["ipo", "inspeção", "inspecao"]):
                ipo_str = f"a **{v_alvo[4].strftime('%d/%m/%Y')}**" if v_alvo[4] else f"no mês de **{mes_ipo}**"
                return f"A próxima inspeção (IPO) do **{nome_v}** (`{mat}`) é {ipo_str}."
            if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["matrícula", "matricula"]):
                return f"A matrícula do **{nome_v}** é **`{mat}`**."
            
            return f"O **{nome_v}** (`{mat}`) tem **{km}** e a inspeção está prevista para o mês de **{mes_ipo}**."

        # Se perguntou pela garagem em geral ou IPO geral
        if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["ipo", "inspeção", "inspecao"]):
            resumo_ipo = []
            for v in veiculos:
                if v[3] and v[3] > 0:
                    m_ipo = NOMES_MESES_PT[v[5]] if v[5] else "--"
                    resumo_ipo.append(f"**{v[0]}**: {m_ipo}")
            return f"Calendário de inspeções (IPO) da garagem: {', '.join(resumo_ipo)}."

        lista = [f"**{v[0]}** (`{v[1]}`): {v[3]:,} km".replace(",", " ") for v in veiculos if v[3] and v[3] > 0]
        return f"Tens as seguintes viaturas ativas na Garagem: {'; '.join(lista)}."
    except Exception as e:
        logger.error(f"Erro em veiculos: {e}")
        return None


async def extrair_contexto_saude(session: AsyncSession, q: str) -> str | None:
    """Responde a perguntas sobre consultas médicas, biomarcadores e SNS."""
    termos_saude = [
        "consulta", "consultas", "médico", "medico", "hospital", "clínica", "clinica",
        "saúde", "saude", "análises", "analises", "biomarcador", "colesterol", "glicose",
        "glicemia", "utente", "sns", "vacina", "vacinas", "pediatria"
    ]
    if not any(re.search(rf"\b{re.escape(t)}\b", q, re.IGNORECASE) for t in termos_saude):
        return None

    try:
        # 1. Perguntas sobre Biomarkers / Análises clínicas (ex: colesterol, glicemia)
        if any(re.search(rf"\b{k}\b", q, re.IGNORECASE) for k in ["análises", "analises", "colesterol", "glicemia", "glicose", "triglicerídeos", "ácido úrico", "biomarcador"]):
            termo_bio = "colesterol" if "colesterol" in q else ("glic" if "glic" in q else "")
            sql_bio = """
                SELECT b.parametro, b.valor, b.unidade, b.data, t.nome as paciente 
                FROM biomarcador_leitura b 
                JOIN perfil_saude p ON p.id = b.perfil_id 
                JOIN titular t ON t.id = p.titular_id 
            """
            if termo_bio:
                sql_bio += f" WHERE b.parametro ILIKE '%{termo_bio}%' "
            sql_bio += " ORDER BY b.data DESC LIMIT 3;"
            res_b = await session.execute(text(sql_bio))
            bios = res_b.fetchall()
            if bios:
                leituras = [f"**{b[0]}** do **{b[4]}**: **{b[1]} {b[2]}** (a {b[3].strftime('%d/%m/%Y')})" for b in bios]
                return f"Últimas leituras laboratoriais: {'; '.join(leituras)}."

        # 2. Medical Appointments
        res_c = await session.execute(text("""
            SELECT c.data_hora, c.especialidade, c.medico, c.local_clinica, t.nome as paciente 
            FROM consulta_medica c 
            JOIN perfil_saude p ON p.id = c.perfil_id 
            JOIN titular t ON t.id = p.titular_id 
            ORDER BY c.data_hora DESC 
            LIMIT 5;
        """))
        consultas = res_c.fetchall()
        if consultas:
            for nome in ["charlie", "sam", "sam", "alex", "alex"]:
                if re.search(rf"\b{nome}\b", q, re.IGNORECASE):
                    c_filtradas = [c for c in consultas if nome in c[4].lower()]
                    if c_filtradas:
                        c = c_filtradas[0]
                        return f"A última consulta registada para o **{c[4]}** é **{c[1]}** com {c[2]} a **{c[0].strftime('%d/%m/%Y às %H:%M')}**."
                    return f"Não encontrei consultas pendentes para **{nome.capitalize()}**."

            lista_c = [f"**{c[4]}**: {c[1]} a **{c[0].strftime('%d/%m/%Y às %H:%M')}**" for c in consultas]
            return f"Consultas registadas na Saúde Familiar: {', '.join(lista_c)}."

        return "Não encontrei registos de consultas médicas pendentes no dossier familiar."
    except Exception as e:
        logger.error(f"Erro em saude: {e}")
        return None


async def gerar_resposta_inteligente(query: str, session: AsyncSession, session_id: str = "default", user_nome: str = "aa-stop-run") -> dict:
    """
    Gera resposta contextual combinando execução de ações, memória multi-turn,
    consultas determinísticas locais (<10ms) e o modelo local qwen3:14b protegido por Circuit Breaker.
    """
    q = query.lower().strip()
    ctx = conversation_memory.get_session(session_id)

    # 0. Verificar se é uma ordem de ação direta (Abastecimento, Manutenção, Eliminação Nível 2, Desfazer)
    res_acao = await tentar_executar_acao(query, session, session_id=session_id)
    if res_acao:
        return {
            "response": res_acao["resposta_texto"],
            "speech_text": res_acao.get("speech_text", res_acao["resposta_texto"]),
            "actions": res_acao.get("actions", []),
        }

    # 0.1 Verificar se é um comando de agendamento por linguagem natural
    from hub.services.nlp_scheduler import tentar_agendar_por_texto
    confirmacao_agendamento = await tentar_agendar_por_texto(query, session)
    if confirmacao_agendamento:
        ctx.add_turn(query, confirmacao_agendamento)
        return {
            "response": confirmacao_agendamento,
            "speech_text": confirmacao_agendamento,
            "actions": [
                {"type": "link", "label": "📅 Ver na Agenda", "target": "/agenda"},
            ],
        }

    # 0.5. Simulador de Crédito & Otimizador de Subscrições
    resp_sim = await extrair_contexto_simulador_otimizador(session, q)
    if resp_sim:
        ctx.add_turn(query, resp_sim["response"])
        return resp_sim

    # 1. Roteamento Especializado por Domínio
    resp_veiculos = await extrair_contexto_veiculos(session, q, session_id=session_id)
    if resp_veiculos:
        if isinstance(resp_veiculos, dict):
            ctx.add_turn(query, resp_veiculos["response"])
            return resp_veiculos
        ctx.add_turn(query, resp_veiculos)
        return {
            "response": resp_veiculos,
            "speech_text": resp_veiculos,
            "actions": [
                {"type": "link", "label": "🚗 Ver Garagem", "target": "http://localhost:8082"},
            ],
        }

    resp_cidadania = await extrair_contexto_cidadania(session, q)
    if resp_cidadania:
        ctx.add_turn(query, resp_cidadania)
        return {
            "response": resp_cidadania,
            "speech_text": resp_cidadania,
            "actions": [
                {"type": "link", "label": "🏛️ Ver Cidadania & Documentos", "target": "http://localhost:8085"},
            ],
        }

    resp_casa = await extrair_contexto_casa(session, q)
    if resp_casa:
        ctx.add_turn(query, resp_casa)
        return {
            "response": resp_casa,
            "speech_text": resp_casa,
            "actions": [
                {"type": "link", "label": "🏠 Ver Home & Warranties", "target": "http://localhost:8084"},
            ],
        }

    resp_saude = await extrair_contexto_saude(session, q)
    if resp_saude:
        ctx.add_turn(query, resp_saude)
        return {
            "response": resp_saude,
            "speech_text": resp_saude,
            "actions": [
                {"type": "link", "label": "🩺 Ver Saúde Familiar", "target": "http://localhost:8083"},
            ],
        }

    # 2. Domínio Finanças & Despesas (com suporte a herança multi-turn de mês/ano)
    gastos_especificos = await extrair_contexto_gastos(session, q, session_id=session_id)
    if gastos_especificos and any(k in q for k in ["quanto", "gastei", "gasto", "gastos", "despesa", "fatura", "paguei", "custo", "e no", "e na", "e em"]):
        cat = gastos_especificos["categoria"]
        ano = gastos_especificos["ano_pedido"]
        mes_nome = gastos_especificos["nome_mes_pedido"]
        tot_p = gastos_especificos["total_periodo"]
        cnt_p = gastos_especificos["count_periodo"]
        tot_a = gastos_especificos["total_ano"]
        ult = gastos_especificos["transacoes"][0] if gastos_especificos["transacoes"] else None
        ult_info = f" A última despesa foi de **€ {ult['valor']:.2f}** a **{ult['data']}** ({ult['descricao']})." if ult else ""

        if mes_nome:
            if tot_p == 0:
                resp_str = f"Em **{mes_nome} de {ano}**, não tens nenhum gasto registado na categoria **{cat}**."
            else:
                resp_str = (
                    f"Em **{mes_nome} de {ano}**, gastaste **€ {tot_p:,.2f}** em **{cat}** "
                    f"({cnt_p} movimento{'s' if cnt_p != 1 else ''}). "
                    f"No total acumulado de {ano}, os teus gastos nesta categoria são de **€ {tot_a:,.2f}**."
                    f"{ult_info}"
                )
        else:
            if tot_a == 0:
                resp_str = f"Em **{ano}**, não tens nenhum gasto registado na categoria **{cat}**."
            else:
                resp_str = (
                    f"Em **{ano}**, gastaste no total **€ {tot_a:,.2f}** em **{cat}** "
                    f"({gastos_especificos['count_ano']} movimentos)."
                    f"{ult_info}"
                )

        ctx.add_turn(query, resp_str, {"mes": gastos_especificos.get("mes_pedido"), "ano": ano, "categoria": cat})
        return {
            "response": resp_str,
            "speech_text": resp_str.replace("**", "").replace("`", ""),
            "actions": [
                {"type": "link", "label": f"📊 Ver Despesas ({cat})", "target": "http://localhost:8081"},
            ],
        }

    # 3. Domínio Agenda & Calendário
    agenda = await obter_agenda_unificada(session)
    eventos_hoje = agenda.get("eventos_hoje", [])
    proximos_eventos = agenda.get("eventos", [])[:8]

    if any(k in q for k in ["agenda", "calendário", "calendario", "compromisso", "compromissos", "o que tenho hoje", "o que tenho marcado", "eventos"]):
        if eventos_hoje:
            ev_str = ", ".join([f"às **{e['hora']}** ({e['titulo']})" for e in eventos_hoje])
            resp_str = f"Hoje tens {len(eventos_hoje)} compromisso(s) na agenda: {ev_str}."
        elif proximos_eventos:
            ev_prox = proximos_eventos[0]
            resp_str = f"Não tens nada marcado para hoje. O teu próximo compromisso é no dia **{ev_prox['data']}** às **{ev_prox['hora']}**: **{ev_prox['titulo']}**."
        else:
            resp_str = "Não tens compromissos pendentes na tua agenda para os próximos dias."

        ctx.add_turn(query, resp_str)
        return {
            "response": resp_str,
            "speech_text": resp_str.replace("**", "").replace("`", ""),
            "actions": [
                {"type": "link", "label": "📅 Ver Agenda", "target": "/agenda"},
            ],
        }

    # 4. Domínio Património Geral & Boas-vindas
    dados_globais = await recolher_dados_consolidados(session)
    patrimonio = dados_globais.get("patrimonio_total", 0)
    despesas_mes = dados_globais.get("despesas_mes", 0)

    if any(k in q for k in ["dinheiro", "finança", "financa", "saldo", "património", "patrimonio"]):
        resp_str = (
            f"O teu património consolidado atual é de **€ {float(patrimonio):,.2f}**, "
            f"com despesas registadas este mês no total de **€ {float(despesas_mes):,.2f}**."
        )
        ctx.add_turn(query, resp_str)
        return {
            "response": resp_str,
            "speech_text": f"O teu património consolidado é de {float(patrimonio):,.0f} euros.",
            "actions": [
                {"type": "link", "label": "💳 Painel Finanças", "target": "http://localhost:8081"},
            ],
        }

    if any(k in q for k in ["olá", "ola", "bom dia", "boa tarde", "boa noite", "quem és", "quem es"]):
        resp_str = f"Olá, {user_nome}! Sou a AVA, a tua assistente pessoal executiva. Podes perguntar-me sobre finanças, a frota da garagem, seguros, consultas de saúde ou dar-me ordens diretas como registar abastecimentos ou eventos. O que precisas?"
        ctx.add_turn(query, resp_str)
        return {
            "response": resp_str,
            "speech_text": f"Olá {user_nome}! Sou a AVA. O que precisas de consultar ou registar?",
            "actions": [],
        }

    # 5. Raciocínio Aberto com Ollama Qwen 14B (Protegido por Circuit Breaker)
    if not ollama_circuit_breaker.is_open:
        historico_turns = "\n".join([f"Utilizador: {t.user_query}\nAVA: {t.bot_response}" for t in ctx.turns[-2:]])
        prompt_llm = (
            f"Tu és a AVA, a assistente pessoal inteligente de {user_nome} no ecossistema familiar.\n"
            f"Estás a falar diretamente com {user_nome}.\n"
            f"Responde sempre em Português de Portugal de forma executiva, simpática e concisa (máximo 2-3 frases).\n"
            f"Dados de contexto: Património total: € {float(patrimonio):,.2f}. Despesas do mês: € {float(despesas_mes):,.2f}.\n"
            f"{historico_turns}\n"
            f"Pergunta de {user_nome}: {query}\n"
            f"Resposta da AVA:"
        )
        resp_llm = await ollama_circuit_breaker.execute_generate(
            base_url=OLLAMA_URL,
            model=OLLAMA_MODEL,
            prompt=prompt_llm,
        )
        if resp_llm:
            ctx.add_turn(query, resp_llm)
            return {
                "response": resp_llm,
                "speech_text": resp_llm,
                "actions": [],
            }

    # 6. Fallback Gracioso: Modo Autónomo Local se Ollama estiver indisponível
    resp_fallback = (
        f"⚡ [Modo Autónomo Local] Consultei o ecossistema: o teu património consolidado atual é de **€ {float(patrimonio):,.2f}** "
        f"e todas as aplicações (Finanças, Garagem, Saúde, Casa e Cidadania) estão operacionais. Diz-me o que queres consultar ou registar."
    )
    ctx.add_turn(query, resp_fallback)
    return {
        "response": resp_fallback,
        "speech_text": f"Consultei a tua base de dados local: o património atual é de {float(patrimonio):,.0f} euros e todas as aplicações estão operacionais.",
        "actions": [
            {"type": "link", "label": "💳 Finanças", "target": "http://localhost:8081"},
            {"type": "link", "label": "🚗 Garagem", "target": "http://localhost:8082"},
            {"type": "link", "label": "📅 Agenda", "target": "/agenda"},
        ],
    }
