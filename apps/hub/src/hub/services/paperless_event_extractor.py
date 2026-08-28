import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hub.paperless_extractor")

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _extrair_data_hora_bilhete(texto: str) -> Optional[tuple[datetime, str]]:
    """
    Extrai data e hora de padrões de bilhetes como:
    'sexta-feira, 4 de setembro de 2026, 14:30' ou 'sábado, 5 de setembro de 2026, 14:30'
    """
    match = re.search(
        r"(?:segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)(?:-feira)?,\s*(\d{1,2})\s+de\s+([a-zA-ZÀ-ÿ]+)\s+de\s+(\d{4}),\s*(\d{1,2}):(\d{2})",
        texto,
        re.IGNORECASE
    )
    if match:
        dia = int(match.group(1))
        mes_nome = match.group(2).lower()
        mes = MESES_PT.get(mes_nome, 9)
        ano = int(match.group(3))
        hora = int(match.group(4))
        minuto = int(match.group(5))
        try:
            dt = datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)
            return dt, f"{dia:02d}/{mes:02d}/{ano} {hora:02d}:{minuto:02d}"
        except Exception:
            pass

    # Padrão DD/MM/YYYY às HH:MM
    match_std = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s+(?:às|as)?\s*(\d{1,2}):(\d{2})", texto)
    if match_std:
        dia, mes, ano, hora, minuto = map(int, match_std.groups())
        try:
            dt = datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)
            return dt, f"{dia:02d}/{mes:02d}/{ano} {hora:02d}:{minuto:02d}"
        except Exception:
            pass

    return None


async def extrair_e_sincronizar_paperless(
    session: AsyncSession,
    paperless_url: str,
    paperless_token: str,
    page_size: int = 40
) -> Dict[str, Any]:
    """
    Varre os documentos recentes no Paperless à procura de bilhetes, eventos e consultas,
    inserindo-os na Agenda Familiar do AVA de forma idempotente.
    """
    if not paperless_url or not paperless_token:
        return {"status": "skipped", "motivo": "Paperless não configurado"}

    url = f"{paperless_url.rstrip('/')}/api/documents/?page_size={page_size}"
    headers = {"Authorization": f"Token {paperless_token}"}

    relatorio = {
        "documentos_analisados": 0,
        "eventos_criados": 0,
        "consultas_criadas": 0,
        "detalhes": []
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning("Erro na API do Paperless: HTTP %s", resp.status_code)
                return relatorio

            dados = resp.json()
            docs = dados.get("results", [])
            relatorio["documentos_analisados"] = len(docs)

            for doc in docs:
                doc_id = doc.get("id")
                title = doc.get("title", "")
                content = doc.get("content", "")

                # 1. Detetor de Bilhetes / Tickets
                if "ticket" in title.lower() or "tickets for:" in content.lower() or "present this entire page" in content.lower():
                    data_hora_info = _extrair_data_hora_bilhete(content)
                    if data_hora_info:
                        dt, fmt = data_hora_info
                        # Extrai nome do bilhete
                        nome_evento = title
                        if "Tickets for: " in title:
                            nome_evento = f"Evento: {title.replace('Tickets for: ', '').strip()}"

                        # Verifica se já existe
                        res_check = await session.execute(text("""
                            SELECT id FROM evento_calendario 
                            WHERE descricao LIKE :ref OR (titulo = :tit AND data_inicio = :dt);
                        """), {
                            "ref": f"%paperless-{doc_id}%",
                            "tit": nome_evento,
                            "dt": dt
                        })
                        if not res_check.scalar():
                            await session.execute(text("""
                                INSERT INTO evento_calendario (titulo, descricao, data_inicio, tipo, local, notificar)
                                VALUES (:titulo, :descricao, :data_inicio, 'pessoal', :local, true);
                            """), {
                                "titulo": nome_evento,
                                "descricao": f"Importado automaticamente do Paperless (Doc #{doc_id}: {title}). {fmt}",
                                "data_inicio": dt,
                                "local": "Local do Evento",
                            })
                            await session.commit()
                            relatorio["eventos_criados"] += 1
                            relatorio["detalhes"].append(f"Criado evento: {nome_evento} ({fmt})")

                # 2. Detetor de Medical Appointments em documentos de clínicas
                if any(k in content.lower() for k in ["consulta", "agendamento", "cuf", "hospital da luz", "trofa saúde", "trofa saude"]):
                    from hub.services.nlp_scheduler import extrair_entidades_consulta
                    ent = extrair_entidades_consulta(content)
                    if ent.get("especialidade") and ent.get("data") and ent.get("hora"):
                        d_str = ent["data"]
                        h_str = ent["hora"]
                        try:
                            dt = datetime.strptime(f"{d_str} {h_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                            esp = ent["especialidade"]
                            paciente = ent.get("paciente", "aa-stop-run")
                            local = ent.get("local") or "Clínica"
                            medico = ent.get("medico", "")

                            # Obter perfil de saúde
                            res_p = await session.execute(text("""
                                SELECT p.id FROM titular t
                                JOIN perfil_saude p ON p.titular_id = t.id
                                WHERE t.nome ILIKE :pac LIMIT 1;
                            """), {"pac": f"%{paciente}%"})
                            perfil_id = res_p.scalar()
                            if not perfil_id:
                                res_def = await session.execute(text("SELECT id FROM perfil_saude LIMIT 1;"))
                                perfil_id = res_def.scalar() or uuid.uuid4()

                            # Verifica duplicado
                            res_c = await session.execute(text("""
                                SELECT id FROM consulta_medica
                                WHERE perfil_id = :pid AND data_hora = :dt AND especialidade = :esp;
                            """), {"pid": perfil_id, "dt": dt, "esp": esp})
                            if not res_c.scalar():
                                await session.execute(text("""
                                    INSERT INTO consulta_medica (
                                        id, perfil_id, data_hora, especialidade, medico, local_clinica,
                                        motivo, custo, concluida, criado_em
                                    ) VALUES (
                                        :id, :pid, :dt, :esp, :med, :loc,
                                        :motivo, 0.00, false, NOW()
                                    );
                                """), {
                                    "id": uuid.uuid4(),
                                    "pid": perfil_id,
                                    "dt": dt,
                                    "esp": esp,
                                    "med": medico,
                                    "loc": local,
                                    "motivo": f"Extraído do Paperless (Doc #{doc_id}: {title})"
                                })
                                await session.commit()
                                relatorio["consultas_criadas"] += 1
                                relatorio["detalhes"].append(f"Criada consulta: {esp} ({d_str} {h_str})")
                        except Exception as e:
                            logger.debug("Erro ao processar consulta de doc #%s: %s", doc_id, e)

                # 3. Detetor de Carta Verde / Seguro Automóvel
                if any(k in content.lower() for k in ["carta verde", "certificado internacional de seguro", "international motor insurance"]):
                    from hub.services.parser_carta_verde import extrair_carta_verde
                    cv = extrair_carta_verde(content)
                    if cv and cv.matricula:
                        # a) Atualizar Ficha do Veículo
                        await session.execute(text("""
                            UPDATE veiculo 
                            SET seguradora = :seg,
                                numero_apolice = :apo,
                                data_fim_seguro = :dfim
                            WHERE matricula = :mat;
                        """), {
                            "seg": cv.seguradora,
                            "apo": cv.numero_apolice,
                            "dfim": cv.data_fim,
                            "mat": cv.matricula
                        })
                        
                        # b) Criar ou Atualizar Contrato
                        res_cont = await session.execute(text("""
                            SELECT id FROM contrato WHERE numero_referencia = :ref OR (tipo = 'seguro_auto' AND nome LIKE :mat_like);
                        """), {
                            "ref": cv.codigo_pais_segurador_numero or cv.numero_apolice,
                            "mat_like": f"%{cv.matricula}%"
                        })
                        if not res_cont.scalar():
                            res_t = await session.execute(text("SELECT id FROM titular WHERE nome ILIKE '%aa-stop-run%' LIMIT 1;"))
                            tid = res_t.scalar()
                            if tid:
                                await session.execute(text("""
                                    INSERT INTO contrato (
                                        id, titular_id, nome, tipo, numero_referencia,
                                        data_inicio, data_fim, renovacao_automatica, dias_aviso_previo,
                                        periodicidade, notas, ativo
                                    ) VALUES (
                                        :id, :tid, :nome, 'seguro_auto', :num_ref,
                                        :dini, :dfim, true, 30,
                                        'semestral', :notas, true
                                    );
                                """), {
                                    "id": uuid.uuid4(),
                                    "tid": tid,
                                    "nome": f"Seguro Auto: {cv.marca_modelo or cv.matricula} ({cv.seguradora})",
                                    "num_ref": cv.codigo_pais_segurador_numero or cv.numero_apolice,
                                    "dini": cv.data_inicio,
                                    "dfim": cv.data_fim,
                                    "notas": f"Importado de Carta Verde (Doc #{doc_id}: {title}). Assistência: {cv.assistencia_viagem or 'N/D'}. Vidros: {cv.quebra_vidros or 'N/D'}."
                                })

                        # c) Lembrete de Renovação na Agenda Familiar
                        res_cal = await session.execute(text("""
                            SELECT id FROM evento_calendario WHERE data_inicio::date = :dfim AND titulo LIKE :tit_like;
                        """), {"dfim": cv.data_fim, "tit_like": f"%{cv.matricula}%"})
                        if not res_cal.scalar():
                            await session.execute(text("""
                                INSERT INTO evento_calendario (titulo, descricao, data_inicio, tipo, local, notificar)
                                VALUES (:tit, :desc, :dt, 'veiculo', :loc, true);
                            """), {
                                "tit": f"Renovação Seguro Auto: {cv.matricula}",
                                "desc": f"Vencimento de apólice {cv.seguradora} ({cv.numero_apolice}). Assistência: {cv.assistencia_viagem or 'N/D'}",
                                "dt": cv.data_fim,
                                "loc": cv.seguradora
                            })
                        await session.commit()
                        relatorio["eventos_criados"] += 1
                        relatorio["detalhes"].append(f"Processada Carta Verde: {cv.matricula} ({cv.seguradora} até {cv.data_fim})")

                # 4. Detetor de Faturas de Energia (EDP / Eletricidade)
                if any(k in content.lower() for k in ["fatura de eletricidade", "fatura de luz", "energia", "utility invoice", "water bill"]):
                    try:
                        # Extrair valor a pagar (ex: 118,73 €)
                        match_val = re.search(r"(?:Quanto tenho a pagar\?|Total a pagar|Valor a pagar)[\s\n]*([0-9]+[.,][0-9]{2})\s*€?", content, re.IGNORECASE)
                        val_pagar = match_val.group(1).replace(",", ".") if match_val else None
                        
                        # Extrair débito direto / vencimento (ex: 8 set 2026 ou 08/09/2026)
                        dt_debito = None
                        match_venc = re.search(r"(?:Débito na minha conta a partir de:|Data limite de pagamento)[\s\n]*(\d{1,2})[ \t]+([A-Za-z]+|\d{1,2})[ \t]+(20\d{2})", content, re.IGNORECASE)
                        if match_venc:
                            d_v = int(match_venc.group(1))
                            m_v_raw = match_venc.group(2).lower()
                            y_v = int(match_venc.group(3))
                            meses_map = {
                                "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "mar": 3, "março": 3,
                                "abr": 4, "abril": 4, "mai": 5, "maio": 5, "jun": 6, "junho": 6,
                                "jul": 7, "julho": 7, "ago": 8, "agosto": 8, "set": 9, "setembro": 9,
                                "out": 10, "outubro": 10, "nov": 11, "novembro": 11, "dez": 12, "dezembro": 12
                            }
                            m_v = meses_map.get(m_v_raw[:3], 1) if not m_v_raw.isdigit() else int(m_v_raw)
                            dt_debito = date(y_v, m_v, d_v)
                        
                        # Número de contrato
                        match_cnt = re.search(r"contrato[\s:]*([0-9]{10,14})", content, re.IGNORECASE)
                        num_cnt = match_cnt.group(1) if match_cnt else "ENERGY"

                        if dt_debito:
                            res_ev_edp = await session.execute(text("""
                                SELECT id FROM evento_calendario WHERE data_inicio::date = :dt AND titulo LIKE '%Utility%';
                            """), {"dt": dt_debito})
                            if not res_ev_edp.scalar():
                                v_str = f"{val_pagar} €" if val_pagar else "Utility"
                                await session.execute(text("""
                                    INSERT INTO evento_calendario (titulo, descricao, data_inicio, tipo, local, notificar)
                                    VALUES (:tit, :desc, :dt, 'financas', 'EDP Comercial', true);
                                """), {
                                    "tit": f"Utility Payment: {v_str}",
                                    "desc": f"Direct debit utility payment (Contract {num_cnt}). Imported from Doc #{doc_id}.",
                                    "dt": dt_debito
                                })
                                await session.commit()
                                relatorio["eventos_criados"] += 1
                                relatorio["detalhes"].append(f"Scheduled utility payment ({v_str} on {dt_debito})")
                    except Exception as e:
                        logger.debug("Error processing utility doc #%s: %s", doc_id, e)

                # 5. Detetor de Compras Tecnológicas com Garantia (PCDIGA, FNAC, Worten)
                if any(k in content.lower() for k in ["pcdiga", "fnac", "worten", "radio popular"]) and any(k in content.lower() for k in ["fatura", "zfat"]):
                    try:
                        # Extrair número de fatura
                        match_fat = re.search(r"(?:FATURA|ZFAT)[\s:Nº]*([A-Za-z0-9/-]+)", content, re.IGNORECASE)
                        num_fat = match_fat.group(1) if match_fat else f"FAT-{doc_id}"

                        # Extrair data da fatura
                        match_dt = re.search(r"\b(20\d{2})[-/](\d{2})[-/](\d{2})\b", content)
                        dt_compra = None
                        if match_dt:
                            dt_compra = date(int(match_dt.group(1)), int(match_dt.group(2)), int(match_dt.group(3)))

                        if dt_compra:
                            dt_garantia = date(dt_compra.year + 3, dt_compra.month, dt_compra.day)
                            res_g = await session.execute(text("""
                                SELECT id FROM contrato WHERE numero_referencia = :ref;
                            """), {"ref": num_fat})
                            if not res_g.scalar():
                                res_t = await session.execute(text("SELECT id FROM titular WHERE nome = 'aa-stop-run' LIMIT 1;"))
                                tid = res_t.scalar()
                                if tid:
                                    await session.execute(text("""
                                        INSERT INTO contrato (
                                            id, titular_id, nome, tipo, numero_referencia,
                                            data_inicio, data_fim, renovacao_automatica, dias_aviso_previo,
                                            periodicidade, notas, ativo
                                        ) VALUES (
                                            :id, :tid, :nome, 'garantia', :ref,
                                            :dini, :dfim, false, 30,
                                            'unica', :notas, true
                                        );
                                    """), {
                                        "id": uuid.uuid4(),
                                        "tid": tid,
                                        "nome": f"Garantia Equipamento ({title[:40]})",
                                        "ref": num_fat,
                                        "dini": dt_compra,
                                        "dfim": dt_garantia,
                                        "notas": f"Garantia legal de 3 anos importada de {title} (Doc #{doc_id}). Válida até {dt_garantia}."
                                    })
                                    await session.commit()
                                    relatorio["eventos_criados"] += 1
                                    relatorio["detalhes"].append(f"Criada garantia tecnológica: {num_fat} (até {dt_garantia})")
                    except Exception as e:
                        logger.debug("Erro ao processar Garantia doc #%s: %s", doc_id, e)


    except Exception as e:
        logger.error("Erro geral no extrator Paperless: %s", e)

    return relatorio
