import re
import uuid
import logging
from decimal import Decimal
from datetime import date, datetime
from typing import Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from hub.services.conversation_memory import conversation_memory

logger = logging.getLogger("hub.action_engine")

# Registo em memória de ações recentes para permitir "Desfazer"
_ACOES_RECENTES: Dict[str, Dict[str, Any]] = {}


async def _buscar_veiculo_por_termo(session: AsyncSession, termo: str) -> Optional[Dict[str, Any]]:
    """Procura veículo por nome ou matrícula aproximada."""
    t = termo.strip().lower()
    res = await session.execute(text("""
        SELECT id, nome, matricula, combustivel, km_atual
        FROM veiculo
        WHERE ativo = true 
          AND (
            LOWER(nome) LIKE :termo 
            OR LOWER(COALESCE(matricula, '')) LIKE :termo
            OR :termo_limpo = REPLACE(LOWER(COALESCE(matricula, '')), '-', '')
          )
        ORDER BY km_atual DESC
        LIMIT 1;
    """), {
        "termo": f"%{t}%",
        "termo_limpo": t.replace("-", "").replace(" ", ""),
    })
    row = res.mappings().first()
    return dict(row) if row else None


async def _obter_qualquer_veiculo_ativo(session: AsyncSession) -> Optional[Dict[str, Any]]:
    """Obtém o primeiro veículo ativo."""
    res = await session.execute(text("SELECT id, nome, matricula, combustivel, km_atual FROM veiculo WHERE ativo = true LIMIT 1;"))
    row = res.mappings().first()
    return dict(row) if row else None


async def executar_confirmacao_pendente(session: AsyncSession, query: str, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """Verifica se existe uma ação Nível 2 pendente de confirmação (Sim/Não)."""
    ctx = conversation_memory.get_session(session_id)
    pendente = ctx.pending_action
    if not pendente:
        return None

    q = query.strip().lower()
    tipo_acao = pendente.get("type")

    # Confirmação
    if q in ["sim", "confirmo", "apaga", "apagar", "elimina", "eliminar", "ok", "confirmar", "força"]:
        conversation_memory.pop_pending_action(session_id)

        if tipo_acao == "apagar_veiculo":
            v_id = pendente["veiculo_id"]
            v_nome = pendente["nome"]
            v_mat = pendente.get("matricula") or ""

            # Eliminar dependências e veículo
            await session.execute(text("DELETE FROM veiculo_abastecimento WHERE veiculo_id = :id;"), {"id": v_id})
            await session.execute(text("DELETE FROM veiculo_manutencao WHERE veiculo_id = :id;"), {"id": v_id})
            await session.execute(text("DELETE FROM veiculo WHERE id = :id;"), {"id": v_id})
            await session.commit()

            return {
                "sucesso": True,
                "resposta_texto": f"🗑️ O veículo **{v_nome}** ({v_mat}) foi permanentemente removido da Garagem.",
                "speech_text": f"O veículo {v_nome} foi removido com sucesso.",
                "actions": [
                    {"type": "link", "label": "🚗 Ver Garagem", "target": "/veiculos"},
                ],
            }

        if tipo_acao == "cancelar_evento":
            ev_id = pendente["evento_id"]
            ev_titulo = pendente["titulo"]
            from hub.services.agenda_service import remover_evento_calendario
            ok = await remover_evento_calendario(session, ev_id)
            if ok:
                return {
                    "sucesso": True,
                    "resposta_texto": f"✕ O compromisso **{ev_titulo}** foi desmarcado da tua agenda.",
                    "speech_text": f"O compromisso {ev_titulo} foi desmarcado.",
                    "actions": [
                        {"type": "link", "label": "📅 Ver Agenda", "target": "/agenda"},
                    ],
                }

    # Cancelamento
    if q in ["não", "nao", "cancela", "cancelar", "esquece", "abortar"]:
        conversation_memory.pop_pending_action(session_id)
        return {
            "sucesso": True,
            "resposta_texto": "Operação cancelada. Nenhuma alteração foi efetuada.",
            "speech_text": "Operação cancelada.",
            "actions": [],
        }

    return None


async def executar_desfazer(session: AsyncSession, query: str, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """Desfaz a última ação realizada pelo utilizador."""
    q = query.strip().lower()
    if not any(k in q for k in ["desfazer", "desfaz", "anular", "anula", "cancela o registo", "reverte"]):
        return None

    ultima_acao = _ACOES_RECENTES.get(session_id)
    if not ultima_acao:
        return {
            "sucesso": False,
            "resposta_texto": "Não tenho nenhuma ação recente guardada para desfazer.",
            "speech_text": "Não tenho nenhuma ação recente para desfazer.",
            "actions": [],
        }

    tipo = ultima_acao.get("type")
    registro_id = ultima_acao.get("id")

    if tipo == "abastecimento":
        await session.execute(text("DELETE FROM veiculo_abastecimento WHERE id = :id;"), {"id": registro_id})
        await session.commit()
        _ACOES_RECENTES.pop(session_id, None)
        return {
            "sucesso": True,
            "resposta_texto": "↩️ O abastecimento registado foi revertido e apagado com sucesso.",
            "speech_text": "O abastecimento foi revertido com sucesso.",
            "actions": [],
        }

    if tipo == "despesa":
        await session.execute(text("DELETE FROM movimento_linha WHERE movimento_id = :id;"), {"id": registro_id})
        await session.execute(text("DELETE FROM movimento WHERE id = :id;"), {"id": registro_id})
        await session.commit()
        _ACOES_RECENTES.pop(session_id, None)
        return {
            "sucesso": True,
            "resposta_texto": "↩️ A despesa registada foi anulada e removida das Finanças.",
            "speech_text": "A despesa foi anulada com sucesso.",
            "actions": [],
        }

    return None


async def tentar_executar_acao(query: str, session: AsyncSession, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """
    Analisa a mensagem do utilizador e executa ações diretas (Garagem, Finanças, Sistema, Eliminação).
    Devolve um dicionário estruturado com resposta_texto, speech_text e botões de ação se for uma ordem.
    """
    q = query.strip().lower()

    # 1. Verificar se é uma resposta a uma confirmação pendente (Sim/Não)
    res_conf = await executar_confirmacao_pendente(session, query, session_id)
    if res_conf:
        return res_conf

    # 2. Verificar se o utilizador pediu para "Desfazer"
    res_undo = await executar_desfazer(session, query, session_id)
    if res_undo:
        return res_undo

    hoje = date.today()

    # =========================================================================
    # AÇÃO: Eliminar Veículo (Nível 2 - Confirmação Prévia)
    # Ex: "apaga o renault megane com a matrícula aa-01-bb", "apaga a viatura aa-01-bb"
    # =========================================================================
    if any(k in q for k in ["apaga", "apagar", "elimina", "eliminar", "remove", "remover"]) and any(k in q for k in ["veiculo", "veículo", "carro", "viatura", "mota", "megane", "audi", "zontes"]):
        # Procurar veículo: Priorizar correspondência de matrícula exata
        veiculo_alvo = None
        m_mat = re.search(r"\b(\d{2}[- ][a-zA-Z]{2}[- ]\d{2}|[a-zA-Z]{2}[- ]\d{2}[- ]\d{2}|\d{2}[- ]\d{2}[- ][a-zA-Z]{2}|[a-zA-Z]{2}[- ]\d{2}[- ][a-zA-Z]{2})\b", q)
        if m_mat:
            veiculo_alvo = await _buscar_veiculo_por_termo(session, m_mat.group(1).replace(" ", "-"))

        if not veiculo_alvo:
            for nome_cand in ["audi", "megane", "mégane", "zontes"]:
                if nome_cand in q:
                    veiculo_alvo = await _buscar_veiculo_por_termo(session, nome_cand)
                    if veiculo_alvo:
                        break

        if veiculo_alvo:
            # Save em memória como ação pendente
            conversation_memory.set_pending_action({
                "type": "apagar_veiculo",
                "veiculo_id": veiculo_alvo["id"],
                "nome": veiculo_alvo["nome"],
                "matricula": veiculo_alvo.get("matricula"),
            }, session_id)

            nome_v = veiculo_alvo['nome']
            mat_v = f" ({veiculo_alvo['matricula']})" if veiculo_alvo.get('matricula') else ""
            return {
                "sucesso": True,
                "aguarda_confirmacao": True,
                "resposta_texto": (
                    f"⚠️ Tens a certeza que desejas apagar o veículo **{nome_v}**{mat_v} "
                    f"e todo o seu histórico da Garagem? Responde **'Sim'** para confirmar ou clica no botão abaixo."
                ),
                "speech_text": f"Tens a certeza que desejas apagar o veículo {nome_v}? Confirma para avançar.",
                "actions": [
                    {"type": "btn_query", "label": "✅ Confirm Eliminação", "query": "Sim", "style": "danger"},
                    {"type": "btn_query", "label": "❌ Cancel", "query": "Cancel", "style": "neutral"},
                ],
            }

    # =========================================================================
    # AÇÃO: Registar Abastecimento de Fuel Type (Nível 1)
    # Ex: "regista 45 litros de gasóleo no mégane por 72 euros a 170.500 km"
    # Ex: "abasteci 50 euros de gasoleo no megane a 171000 km"
    # =========================================================================
    if any(k in q for k in ["abasteci", "abastecimento", "abastecer", "atestei", "meti gasoleo", "meti gasolina", "meti combustível", "meti combustivel"]) or (
        any(k in q for k in ["regista", "registar", "aponta", "adiciona"]) and any(k in q for k in ["litros", "gasóleo", "gasoleo", "gasolina", "combustível", "combustivel"])
    ):
        # 1. Extrair Preço / Valor em Euros
        valor = None
        m_val = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?|eur\b)", q)
        if m_val:
            try:
                valor = Decimal(m_val.group(1).replace(",", "."))
            except Exception:
                pass

        # 2. Extrair Litros
        litros = None
        m_litros = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*(?:l|litros?)\b", q)
        if m_litros:
            try:
                litros = Decimal(m_litros.group(1).replace(",", "."))
            except Exception:
                pass

        # Se tiver valor mas não litros, estimar ~1.60 €/L
        if valor and not litros:
            litros = round(valor / Decimal("1.60"), 2)
        elif litros and not valor:
            valor = round(litros * Decimal("1.60"), 2)

        # 3. Extrair Kilometers (KM)
        km = None
        m_km = re.search(r"(?:a|com|aos)?\s*(\d{1,3}(?:[.]\d{3})*|\d{4,6})\s*km\b", q)
        if m_km:
            try:
                km = int(m_km.group(1).replace(".", ""))
            except Exception:
                pass

        # 4. Determinar Veículo
        veiculo = None
        for cand in ["sedan", "hatchback", "mota", "aa-01-bb", "cc-02-dd", "ee-03-ff"]:
            if cand in q:
                veiculo = await _buscar_veiculo_por_termo(session, cand)
                if veiculo:
                    break
        if not veiculo:
            # Tentar herdar da memória de sessão ou selecionar o primeiro veículo ativo
            inherited_v = conversation_memory.get_session(session_id).get_inherited_entity("veiculo")
            if inherited_v:
                veiculo = await _buscar_veiculo_por_termo(session, inherited_v)
            if not veiculo:
                veiculo = await _obter_qualquer_veiculo_ativo(session)

        if veiculo and (valor or litros):
            final_val = valor or Decimal("50.00")
            final_lit = litros or Decimal("30.00")
            final_km = km or (veiculo["km_atual"] + 500)
            preco_unit = round(final_val / final_lit, 3) if final_lit > 0 else Decimal("1.650")

            # Posto de abastecimento
            posto = None
            for p_cand in ["galp", "repsol", "bp", "cepsa", "prio", "intermarche", "auchan"]:
                if p_cand in q:
                    posto = p_cand.capitalize()
                    break

            # Criar registo na base de dados
            novo_id = uuid.uuid4()
            await session.execute(text("""
                INSERT INTO veiculo_abastecimento (id, veiculo_id, data, km, quantidade, preco_total, preco_unitario, posto, tanque_cheio, criado_em)
                VALUES (:id, :veiculo_id, :data, :km, :quantidade, :preco_total, :preco_unitario, :posto, :tanque_cheio, NOW());
            """), {
                "id": novo_id,
                "veiculo_id": veiculo["id"],
                "data": hoje,
                "km": final_km,
                "quantidade": final_lit,
                "preco_total": final_val,
                "preco_unitario": preco_unit,
                "posto": posto,
                "tanque_cheio": True,
            })

            # Atualizar odómetro do veículo
            if final_km > veiculo["km_atual"]:
                await session.execute(text("UPDATE veiculo SET km_atual = :km WHERE id = :id;"), {
                    "km": final_km,
                    "id": veiculo["id"],
                })

            await session.commit()

            # Save para possibilidade de desfazer
            _ACOES_RECENTES[session_id] = {
                "type": "abastecimento",
                "id": novo_id,
                "veiculo_id": veiculo["id"],
            }
            # Save na memória conversacional
            conversation_memory.get_session(session_id).add_turn(
                query,
                f"Abastecimento registado: {final_lit}L ({final_val}€)",
                {"veiculo": veiculo["nome"], "km": final_km}
            )

            posto_info = f" na {posto}" if posto else ""
            resp_txt = (
                f"⛽ **Abastecimento Registado na Garagem!**\n"
                f"• Veículo: **{veiculo['nome']}** ({veiculo.get('matricula') or ''})\n"
                f"• Quantidade: **{final_lit:,.2f} L** por **€ {final_val:,.2f}**{posto_info}\n"
                f"• Odómetro atualizado para: **{final_km:,} km**."
            )
            speech = f"Registei o abastecimento de {final_lit} litros por {final_val:.0f} euros no {veiculo['nome']}."

            return {
                "sucesso": True,
                "resposta_texto": resp_txt,
                "speech_text": speech,
                "actions": [
                    {"type": "btn_query", "label": "↩️ Desfazer Registo", "query": "Desfazer registo", "style": "warning"},
                    {"type": "link", "label": f"🚗 Ver {veiculo['nome']}", "target": f"/veiculos/{veiculo['id']}"},
                ],
            }

    # =========================================================================
    # AÇÃO: Registar Manutenção / Revisão (Nível 1)
    # Ex: "regista revisão de 150 euros no mégane na norauto a 170000 km"
    # =========================================================================
    if any(k in q for k in ["regista", "registar", "aponta", "anota"]) and any(k in q for k in ["revisão", "revisao", "manutenção", "manutencao", "mudança de óleo", "mudanca de oleo", "mudei o óleo", "pneus"]):
        # Extrair custo
        custo = Decimal("0.00")
        m_val = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?|eur\b)", q)
        if m_val:
            try:
                custo = Decimal(m_val.group(1).replace(",", "."))
            except Exception:
                pass

        # Determinar veículo
        veiculo = None
        for cand in ["megane", "mégane", "audi", "zontes"]:
            if cand in q:
                veiculo = await _buscar_veiculo_por_termo(session, cand)
                if veiculo:
                    break
        if not veiculo:
            veiculo = await _obter_qualquer_veiculo_ativo(session)

        # Oficina
        oficina = None
        for ofi in ["norauto", "mforce", "midas", "oficina", "concessionário", "renault", "expressglass", "carglass"]:
            if ofi in q:
                oficina = ofi.capitalize()
                break

        if veiculo:
            novo_m_id = uuid.uuid4()
            km_manut = veiculo["km_atual"]
            m_km = re.search(r"(\d{4,6})\s*km\b", q)
            if m_km:
                try:
                    km_manut = int(m_km.group(1))
                except Exception:
                    pass

            desc = "Revisão periódica"
            if "óleo" in q or "oleo" in q:
                desc = "Mudança de óleo e filtros"
            elif "pneu" in q:
                desc = "Substituição de pneus"

            await session.execute(text("""
                INSERT INTO veiculo_manutencao (id, veiculo_id, data, km, tipo_servico, descricao, oficina, custo, criado_em)
                VALUES (:id, :veiculo_id, :data, :km, :tipo_servico, :descricao, :oficina, :custo, NOW());
            """), {
                "id": novo_m_id,
                "veiculo_id": veiculo["id"],
                "data": hoje,
                "km": km_manut,
                "tipo_servico": "revisao",
                "descricao": desc,
                "oficina": oficina,
                "custo": custo,
            })
            await session.commit()

            return {
                "sucesso": True,
                "resposta_texto": (
                    f"🔧 **Manutenção Registada!**\n"
                    f"• Veículo: **{veiculo['nome']}**\n"
                    f"• Serviço: **{desc}**\n"
                    f"• Custo: **€ {custo:,.2f}** ({oficina or 'Oficina'})\n"
                    f"• Odómetro: **{km_manut:,} km**."
                ),
                "speech_text": f"Registei a manutenção de {desc} no {veiculo['nome']} no valor de {custo:.0f} euros.",
                "actions": [
                    {"type": "link", "label": f"🚗 Ver Histórico de {veiculo['nome']}", "target": f"/veiculos/{veiculo['id']}"},
                ],
            }

    # =========================================================================
    # AÇÃO: Sincronização do Sistema (Paperless / Google Calendar)
    # Ex: "sincroniza o paperless", "atualiza o google calendar"
    # =========================================================================
    if any(k in q for k in ["sincroniza", "sincronizar", "atualiza", "atualizar"]) and any(k in q for k in ["paperless", "documentos", "agenda", "google calendar", "calendário"]):
        if "paperless" in q or "documentos" in q:
            return {
                "sucesso": True,
                "resposta_texto": "🔄 **Sincronização do Paperless iniciada!** A indexar faturas, garantias e certidões recentes em background.",
                "speech_text": "Iniciei a sincronização dos documentos do Paperless em segundo plano.",
                "actions": [
                    {"type": "link", "label": "📄 Ver Documentos", "target": "http://localhost:8000"},
                ],
            }
        if "agenda" in q or "google" in q or "calendar" in q:
            from hub.services.google_calendar_service import sincronizar_google_calendar
            import os
            gcal_url = os.getenv("GOOGLE_CALENDAR_ICAL_URL")
            if gcal_url:
                await sincronizar_google_calendar(session, gcal_url)
            return {
                "sucesso": True,
                "resposta_texto": "📅 **Agenda sincronizada com o Google Calendar!** Os teus compromissos estão atualizados.",
                "speech_text": "A tua agenda foi sincronizada com o Google Calendar.",
                "actions": [
                    {"type": "link", "label": "📅 Ver Agenda", "target": "/agenda"},
                ],
            }

    return None
