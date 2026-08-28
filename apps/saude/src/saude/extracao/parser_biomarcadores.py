import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import pypdf


@dataclass
class BiomarcadorExtraido:
    categoria: str
    parametro: str
    valor: Decimal
    unidade: str
    ref_min: Decimal | None = None
    ref_max: Decimal | None = None


# Catálogo abrangente com padrões multi-laboratório (Germano de Sousa, CUF, Unilabs, Joaquim Chaves, etc.)
PARAMETROS_CATALOGO = [
    # ── METABOLISMO & GLICÉMIA ──
    {
        "parametro": "Glicémia",
        "categoria": "Metabolismo",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Glicose|Glicémia|Glicemia(?:\s+em\s+jejum|\s+basal)?)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": Decimal("70"),
        "ref_max": Decimal("110"),
    },
    {
        "parametro": "HbA1c (Hemoglobina Glicada)",
        "categoria": "Metabolismo",
        "unidade": "%",
        "padrao_regex": r"(?:Hemoglobina\s+Glicada(?:\s*\(A1c\))?(?:\s*\[NGSP\])?|HbA1c)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*%",
        "ref_min": Decimal("4.0"),
        "ref_max": Decimal("5.8"),
    },

    # ── PERFIL LIPÍDICO ──
    {
        "parametro": "Colesterol Total",
        "categoria": "Perfil Lipídico",
        "unidade": "mg/dL",
        "padrao_regex": r"Colesterol\s+Total[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("190"),
    },
    {
        "parametro": "Colesterol HDL",
        "categoria": "Perfil Lipídico",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Colesterol\s+HDL|HDL\s+Colesterol)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": Decimal("40"),
        "ref_max": None,
    },
    {
        "parametro": "Colesterol LDL",
        "categoria": "Perfil Lipídico",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Colesterol\s+LDL(?:\s+direto)?|LDL\s+Colesterol)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("115"),
    },
    {
        "parametro": "Triglicéridos",
        "categoria": "Perfil Lipídico",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Triglicéridos|Triglicerídeos|Trigliceridos)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("150"),
    },

    # ── HEMOGRAMA & COAGULAÇÃO ──
    {
        "parametro": "Hemoglobina",
        "categoria": "Hemograma",
        "unidade": "g/dL",
        "padrao_regex": r"\bHemoglobina(?:\s*\(Hgb\))?[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:g/d[Ll])?",
        "ref_min": Decimal("13.0"),
        "ref_max": Decimal("17.0"),
    },
    {
        "parametro": "Eritrócitos",
        "categoria": "Hemograma",
        "unidade": "10^6/µL",
        "padrao_regex": r"\bEritrócitos\b[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:x10\^12/L|x\s*106/µl)?",
        "ref_min": Decimal("4.50"),
        "ref_max": Decimal("5.50"),
    },
    {
        "parametro": "Hematócrito",
        "categoria": "Hemograma",
        "unidade": "%",
        "padrao_regex": r"(?:Volume\s+Globular\s*/\s*Hematócrito(?:\s*\(Hct\))?|Hematócrito)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*%",
        "ref_min": Decimal("40.0"),
        "ref_max": Decimal("50.0"),
    },
    {
        "parametro": "Volume Globular Médio (VGM)",
        "categoria": "Hemograma",
        "unidade": "fl",
        "padrao_regex": r"(?:V\.G\.M\.|Volume\s+Globular\s+Médio)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*fl",
        "ref_min": Decimal("80.0"),
        "ref_max": Decimal("97.0"),
    },
    {
        "parametro": "Leucócitos",
        "categoria": "Hemograma",
        "unidade": "10^3/µL",
        "padrao_regex": r"\bLeucócitos\b[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)",
        "ref_min": Decimal("4.0"),
        "ref_max": Decimal("10.0"),
    },
    {
        "parametro": "Neutrófilos",
        "categoria": "Hemograma",
        "unidade": "%",
        "padrao_regex": r"\bNeutrófilos\b[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*%",
        "ref_min": Decimal("40.0"),
        "ref_max": Decimal("80.0"),
    },
    {
        "parametro": "Linfócitos",
        "categoria": "Hemograma",
        "unidade": "%",
        "padrao_regex": r"\bLinfócitos\b[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*%",
        "ref_min": Decimal("20.0"),
        "ref_max": Decimal("40.0"),
    },
    {
        "parametro": "Plaquetas",
        "categoria": "Hemograma",
        "unidade": "10^3/µL",
        "padrao_regex": r"(?:Plaquetas|Número(?=\s+\d+\s+x10\^9/L))[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)",
        "ref_min": Decimal("150"),
        "ref_max": Decimal("400"),
    },
    {
        "parametro": "Velocidade Sedimentação (VS)",
        "categoria": "Hemograma",
        "unidade": "mm",
        "padrao_regex": r"Velocidade\s+de\s+Sedimentação(?:\s+na\s+1ª\s+hora)?[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)",
        "ref_min": None,
        "ref_max": Decimal("15"),
    },

    # ── FUNÇÃO RENAL & HEPÁTICA ──
    {
        "parametro": "Creatinina",
        "categoria": "Fígado & Rins",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Creatininémia|Creatinina(?:\s+no\s+soro)?)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": Decimal("0.70"),
        "ref_max": Decimal("1.30"),
    },
    {
        "parametro": "TFGe",
        "categoria": "Fígado & Rins",
        "unidade": "mL/min",
        "padrao_regex": r"TFGe(?:\s*\[CKD-EPI\s*\d+\])?[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)",
        "ref_min": Decimal("60"),
        "ref_max": None,
    },
    {
        "parametro": "Ureia",
        "categoria": "Fígado & Rins",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Urémia|\bUreia\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("50"),
    },
    {
        "parametro": "Azoto Ureico (BUN)",
        "categoria": "Fígado & Rins",
        "unidade": "mg/dL",
        "padrao_regex": r"Azoto\s+Ureico(?:\s*\(BUN\))?[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": Decimal("6"),
        "ref_max": Decimal("20"),
    },
    {
        "parametro": "Ácido Úrico",
        "categoria": "Fígado & Rins",
        "unidade": "mg/dL",
        "padrao_regex": r"(?:Uricémia|Ácido\s+Úrico|Acido\s+Urico)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mg/d[Ll])?",
        "ref_min": Decimal("3.5"),
        "ref_max": Decimal("7.2"),
    },
    {
        "parametro": "TGO (AST)",
        "categoria": "Fígado & Rins",
        "unidade": "U/L",
        "padrao_regex": r"(?:Aspartato\s+Aminotransferase(?:\s*\(AST\)|\s*\(TGO\))?|\bAST\b|\bTGO\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:U/[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("37"),
    },
    {
        "parametro": "TGP (ALT)",
        "categoria": "Fígado & Rins",
        "unidade": "U/L",
        "padrao_regex": r"(?:Alanina\s+Aminotransferase(?:\s*\(ALT\)|\s*\(TGP\))?|\bALT\b|\bTGP\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:U/[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("50"),
    },
    {
        "parametro": "GGT",
        "categoria": "Fígado & Rins",
        "unidade": "U/L",
        "padrao_regex": r"(?:Gama[- ]Glutamil[- ]Transpeptidase|Gama[- ]Glutamil[- ]Transferase|\bGGT\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:U/[Ll])?",
        "ref_min": None,
        "ref_max": Decimal("73"),
    },

    # ── VITAMINAS & MINERAIS ──
    {
        "parametro": "Vitamina D",
        "categoria": "Vitaminas",
        "unidade": "ng/mL",
        "padrao_regex": r"(?:25-Hidroxivitamina\s+D|Vitamina\s+D(?:\s*\(?25-OH\)?)?)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:ng/m[Ll])?",
        "ref_min": Decimal("30.0"),
        "ref_max": Decimal("100.0"),
    },
    {
        "parametro": "Vitamina B12",
        "categoria": "Vitaminas",
        "unidade": "pg/mL",
        "padrao_regex": r"Vitamina\s+B12[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:pg/m[Ll])?",
        "ref_min": Decimal("200"),
        "ref_max": Decimal("900"),
    },
    {
        "parametro": "Ferritina",
        "categoria": "Vitaminas",
        "unidade": "ng/mL",
        "padrao_regex": r"Ferritina[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:ng/m[Ll])?",
        "ref_min": Decimal("30"),
        "ref_max": Decimal("400"),
    },

    # ── ELETRÓLITOS ──
    {
        "parametro": "Sódio",
        "categoria": "Eletrólitos",
        "unidade": "mmol/L",
        "padrao_regex": r"(?:Natrémia|Sódio)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mmol/l)?",
        "ref_min": Decimal("136.0"),
        "ref_max": Decimal("145.0"),
    },
    {
        "parametro": "Potássio",
        "categoria": "Eletrólitos",
        "unidade": "mmol/L",
        "padrao_regex": r"(?:Kaliémia|Potássio)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mmol/l)?",
        "ref_min": Decimal("3.5"),
        "ref_max": Decimal("5.1"),
    },
    {
        "parametro": "Cloro",
        "categoria": "Eletrólitos",
        "unidade": "mmol/L",
        "padrao_regex": r"(?:Clorémia|Cloro)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mmol/l)?",
        "ref_min": Decimal("98.0"),
        "ref_max": Decimal("107.0"),
    },

    # ── TIROIDE ──
    {
        "parametro": "TSH",
        "categoria": "Tiroide",
        "unidade": "µUI/mL",
        "padrao_regex": r"(?:Tireoestimulina(?:\s*\(TSH\))?|\bTSH\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:mUI/l|µUI/m[Ll]|uUI/m[Ll])?",
        "ref_min": Decimal("0.350"),
        "ref_max": Decimal("5.500"),
    },
    {
        "parametro": "FT4",
        "categoria": "Tiroide",
        "unidade": "ng/dL",
        "padrao_regex": r"(?:Tiroxina\s+Livre(?:\s*\(FT4\))?|\bFT4\b)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:ng/dl)?",
        "ref_min": Decimal("0.80"),
        "ref_max": Decimal("1.76"),
    },
    # ── ALERGOLOGIA & IMUNOLOGIA ──
    {
        "parametro": "Imunoglobulina E Total (IgE)",
        "categoria": "Alergologia",
        "unidade": "UI/mL",
        "padrao_regex": r"(?:Imunoglobulina\s+E\s+Total|IgE\s+Total)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:UI/ml|kU/l)?",
        "ref_min": None,
        "ref_max": Decimal("60.0"),
    },
    {
        "parametro": "Siderémia (Ferro)",
        "categoria": "Metabolismo",
        "unidade": "µg/dL",
        "padrao_regex": r"(?:Siderémia|Sideremia|Ferro\s+Sérico)[ \t]*[:=]?[ \t]*(\d+(?:[.,]\d+)?)[ \t]*(?:µg/dl|ug/dl)?",
        "ref_min": Decimal("20.0"),
        "ref_max": Decimal("100.0"),
    },
]


def extrair_texto_de_pdf(ficheiro_bytes: bytes) -> str:
    """Extrai texto legível de um ficheiro PDF em memória."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(ficheiro_bytes))
        textos = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                textos.append(t)
        return "\n".join(textos)
    except Exception:
        return ""


def extrair_titular_sugerido(texto: str) -> str | None:
    """Identifica o nome do utente/titular no cabeçalho do exame (ex: aa-stop-run, Member, Junior)."""
    t = texto.lower()
    if "junior" in t or "charlie" in t or "pediatria" in t:
        return "Junior"
    if "member" in t or "sam" in t:
        return "Member"
    if "aa-stop-run" in t or "alex" in t or "utente" in t or "paciente" in t:
        return "aa-stop-run"
    return None


def extrair_laboratorio(texto: str) -> str:
    """Identifica o laboratório / clínica emissora do relatório de forma genérica."""
    match = re.search(r"(?:Laboratório|Laboratory|Clínica|Clinic|Hospital|Diagnostics?)[\s:]*([A-Za-z0-9\s&.-]+?)(?=\n|\r|$)", texto, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    linhas = [l.strip() for l in texto.strip().split("\n") if l.strip()]
    if linhas and len(linhas[0]) > 3 and not re.search(r"\b(utente|paciente|patient|data|date)\b", linhas[0], re.IGNORECASE):
        return linhas[0]
    return "Clinical Diagnostic Laboratory"


def extrair_data_relatorio(texto: str) -> date:
    """
    Extrai com rigor a Data de Colheita do relatório clínico (data biológica do sangue).
    Prioriza sempre 'Data de Colheita' sobre 'Data de Emissão' ou 'Relatório'.
    """
    # 1. Prioridade máxima: Data de Colheita (ex: "Data de Colheita 04-04-2024" ou "Colheita: 29/07/2025")
    match = re.search(r"(?:Data\s+de\s+Colheita|Colheita)[\s:]*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", texto, re.IGNORECASE)
    if match:
        d, m, y = map(int, match.groups())
        try:
            return date(y, m, d)
        except Exception:
            pass

    # 2. Emissão / Relatório se colheita não explícita
    match = re.search(r"(?:Data\s+de\s+Emissão|Data\s+Emissão|Relatório|Inscrição)[\s:]*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", texto, re.IGNORECASE)
    if match:
        d, m, y = map(int, match.groups())
        try:
            return date(y, m, d)
        except Exception:
            pass

    return date.today()


def extrair_biomarcadores(texto: str) -> list[BiomarcadorExtraido]:
    """Extrai todos os biomarcadores encontrados no texto do relatório sem contaminação entre linhas."""
    resultados: list[BiomarcadorExtraido] = []
    if not texto:
        return resultados

    # Processar linha a linha ou segmentos lineares para garantir integridade tabular
    linhas = texto.splitlines()

    for item in PARAMETROS_CATALOGO:
        regex = re.compile(item["padrao_regex"], re.IGNORECASE)
        
        # Procurar por correspondência linha a linha primeiro
        encontrado = False
        for linha in linhas:
            m = regex.search(linha)
            if m:
                raw_val = m.group(1).replace(",", ".")
                try:
                    val = Decimal(raw_val)
                    resultados.append(
                        BiomarcadorExtraido(
                            categoria=item["categoria"],
                            parametro=item["parametro"],
                            valor=val,
                            unidade=item["unidade"],
                            ref_min=item["ref_min"],
                            ref_max=item["ref_max"],
                        )
                    )
                    encontrado = True
                    break
                except Exception:
                    continue

        # Se não encontrou linha a linha, tenta na totalidade mas com limite horizontal
        if not encontrado:
            m = regex.search(texto)
            if m:
                raw_val = m.group(1).replace(",", ".")
                try:
                    val = Decimal(raw_val)
                    resultados.append(
                        BiomarcadorExtraido(
                            categoria=item["categoria"],
                            parametro=item["parametro"],
                            valor=val,
                            unidade=item["unidade"],
                            ref_min=item["ref_min"],
                            ref_max=item["ref_max"],
                        )
                    )
                except Exception:
                    continue

    return resultados
