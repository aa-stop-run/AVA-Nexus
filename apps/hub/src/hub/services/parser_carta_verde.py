import re
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class CartaVerdeExtraida:
    matricula: str
    marca_modelo: Optional[str]
    seguradora: str
    numero_apolice: str
    codigo_pais_segurador_numero: Optional[str]
    numero_segurnet: Optional[str]
    data_inicio: date
    data_fim: date
    tomador_nome: Optional[str]
    tomador_morada: Optional[str]
    assistencia_viagem: Optional[str]
    quebra_vidros: Optional[str]
    telefone_seguradora: Optional[str]


def extrair_carta_verde(texto: str) -> Optional[CartaVerdeExtraida]:
    """
    Extrai dados estruturados de um Certificado Internacional de Seguro Automóvel (Carta Verde).
    Suporta o modelo padronizado pelo Gabinete Português de Carta Verde / CIMPAS.
    """
    if not texto:
        return None

    t = texto.replace("\r", "")

    # 1. Plate Portuguesa
    match_mat = re.search(r"\b([0-9]{2}-[A-Z]{2}-[0-9]{2}|[0-9]{2}-[0-9]{2}-[A-Z]{2}|[A-Z]{2}-[0-9]{2}-[0-9]{2}|[A-Z]{2}-[0-9]{2}-[A-Z]{2})\b", t)
    if match_mat:
        matricula = match_mat.group(1).upper()
    else:
        return None

    # 2. Datas de Expiry Date (Box 3: VÁLIDO DE [DD MM AAAA] A [DD MM AAAA])
    data_inicio = None
    data_fim = None

    datas_encontradas = re.findall(r"\b(\d{2})[ \t]+(\d{2})[ \t]+(20\d{2})\b", t)
    if len(datas_encontradas) >= 2:
        d1, m1, y1 = map(int, datas_encontradas[0])
        d2, m2, y2 = map(int, datas_encontradas[1])
        try:
            data_inicio = date(y1, m1, d1)
            data_fim = date(y2, m2, d2)
        except Exception:
            pass

    if not data_inicio or not data_fim:
        datas_slash = re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b", t)
        if len(datas_slash) >= 2:
            d1, m1, y1 = map(int, datas_slash[0])
            d2, m2, y2 = map(int, datas_slash[1])
            try:
                data_inicio = date(y1, m1, d1)
                data_fim = date(y2, m2, d2)
            except Exception:
                pass

    if not data_inicio or not data_fim:
        return None

    # 3. Insurance Co.
    seguradora = "Insurance Co."
    t_lower = t.lower()
    if "divina" in t_lower:
        seguradora = "Divina Seguros"
    elif "fidelidade" in t_lower:
        seguradora = "Fidelidade"
    elif "tranquilidade" in t_lower:
        seguradora = "Tranquilidade"
    elif "allianz" in t_lower:
        seguradora = "Allianz"
    elif "zurich" in t_lower:
        seguradora = "Zurich"
    elif "generali" in t_lower:
        seguradora = "Generali"
    elif "lusitania" in t_lower or "lusitânia" in t_lower:
        seguradora = "Lusitania"
    elif "logo" in t_lower:
        seguradora = "Logo"
    elif "mapfre" in t_lower:
        seguradora = "Mapfre"
    elif "ageas" in t_lower:
        seguradora = "Ageas Seguros"
    elif "ok! telescopio" in t_lower or "ok seguros" in t_lower:
        seguradora = "OK! Seguros"
    else:
        match_emit = re.search(r"Este certificado foi emitido por:[\s]*([A-Za-zÀ-ÿ\s,.]+?)(?=\n|Calle|Rua|Av|$)", t)
        if match_emit:
            seguradora = match_emit.group(1).strip()

    # 4. Código do País / Segurador / Número da Policy No. (Box 4)
    codigo_completo = None
    numero_apolice = None
    match_apolice = re.search(r"([A-Z])\s*/\s*(\d{3,5})\s*/\s*([A-Za-z0-9]+)", t)
    if match_apolice:
        codigo_completo = f"{match_apolice.group(1)} / {match_apolice.group(2)} / {match_apolice.group(3)}"
        numero_apolice = match_apolice.group(3)
    else:
        match_num = re.search(r"(?:Policy No.|Apolice|Número|Contrato)[\s:Nºno]*([0-9]{7,15})", t, re.IGNORECASE)
        if match_num:
            numero_apolice = match_num.group(1)
            codigo_completo = numero_apolice
        else:
            numero_apolice = "S/N"

    # 5. Número Segurnet
    numero_segurnet = None
    match_segurnet = re.search(r"Segurnet[:\s]*([A-Z0-9]{8,15})", t, re.IGNORECASE)
    if match_segurnet:
        numero_segurnet = match_segurnet.group(1).strip()

    # 6. Marca / Modelo do Veículo (Box 7)
    marca_modelo = None
    match_marca = re.search(r"(?:Marca do veículo|Marca)\s*\n?.*?\b([A-Z]{3,}\s+[A-Za-zÀ-ÿ0-9.\s]+?)(?=\s*(?:\n|DIA|MÊS|ANO|8\.|Categoria|$))", t)
    if match_marca:
        candidato = match_marca.group(1).strip()
        candidato = re.sub(r"^[A-G]\s+", "", candidato).strip()
        marca_modelo = candidato
    else:
        for marca in ["RENAULT", "Renault", "BMW", "Mercedes", "Audi", "Peugeot", "Citroen", "Volkswagen", "Toyota", "Nissan", "Seat", "Commuter"]:
            if marca in t:
                m_sub = re.search(rf"({marca}\s+[A-Za-zÀ-ÿ0-9.\s]+?)(?=\s*(?:\n|DIA|MÊS|ANO|8\.|$))", t)
                if m_sub:
                    marca_modelo = m_sub.group(1).strip()
                    break

    # 7. Tomador do Seguro e Endereço (Box 9)
    tomador_nome = None
    tomador_morada = None
    match_tomador = re.search(r"9\.\s*Nome e endereço do Tomador do Seguro[^\n]*\n+([A-Za-zÀ-ÿ\s]+?)(?=\n[A-Za-zÀ-ÿ0-9\s,/-]+?(?:Baguim|Porto|Lisboa|\d{4}-\d{3})|\n10\.|\nCalle|$)", t)
    if match_tomador:
        tomador_nome = match_tomador.group(1).strip()

    match_morada = re.search(r"((?:Rua|Av\.|Avenida|Praceta|Travessa)[A-Za-zÀ-ÿ0-9\s,./-]+?\d{4}-\d{3}[A-Za-zÀ-ÿ\s-]*)", t)
    if match_morada:
        tomador_morada = match_morada.group(1).strip()

    # 8. Telefones de Emergência
    assistencia_viagem = None
    match_ass = re.search(r"Assistência em Viagem[^\n]*\n*(?:[^\n]*\n*)*?(\+?351[\s\d]{9,12}|\b30\d[\s\d]{6,9}\b|\b21\d[\s\d]{6,9}\b|\b808[\s\d]{6,9}\b)", t, re.IGNORECASE)
    if match_ass:
        assistencia_viagem = match_ass.group(1).strip()

    quebra_vidros = None
    match_vidro = re.search(r"(?:quebra de Vidro|vidros)[^\n]*\n*(?:Nº Azul:\s*)?(\b808[\s\d]{6,9}\b|\+?351[\s\d]{9,12})", t, re.IGNORECASE)
    if match_vidro:
        quebra_vidros = match_vidro.group(1).strip()

    telefone_seguradora = None
    match_tel_seg = re.search(r"Telefone Portugal[:\s]*(\+?351[\s\d]{9,12}|\b21\d[\s\d]{6,9}\b)", t, re.IGNORECASE)
    if match_tel_seg:
        telefone_seguradora = match_tel_seg.group(1).strip()

    return CartaVerdeExtraida(
        matricula=matricula,
        marca_modelo=marca_modelo,
        seguradora=seguradora,
        numero_apolice=numero_apolice,
        codigo_pais_segurador_numero=codigo_completo,
        numero_segurnet=numero_segurnet,
        data_inicio=data_inicio,
        data_fim=data_fim,
        tomador_nome=tomador_nome,
        tomador_morada=tomador_morada,
        assistencia_viagem=assistencia_viagem,
        quebra_vidros=quebra_vidros,
        telefone_seguradora=telefone_seguradora,
    )
