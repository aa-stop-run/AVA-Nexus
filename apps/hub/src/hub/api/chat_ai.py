from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from hub.db import get_session
from hub.services.ai_agent import gerar_resposta_inteligente
from hub.services.auth_service import validar_token_sessao

router = APIRouter(prefix="/api", tags=["chat"])


class ChatQuery(BaseModel):
    query: str
    session_id: str = "default"


@router.post("/chat")
async def chat_interaction(payload: ChatQuery, request: Request, session: AsyncSession = Depends(get_session)):
    """Responde a perguntas em linguagem natural e voz sobre o ecossistema com acesso a dados reais e LLM."""
    cookie_token = request.cookies.get("ava_session_token")
    user = validar_token_sessao(cookie_token)
    user_nome = user["nome"] if user else "aa-stop-run"

    resposta = await gerar_resposta_inteligente(payload.query, session, session_id=payload.session_id, user_nome=user_nome)
    if isinstance(resposta, dict):
        return {
            "query": payload.query,
            "response": resposta.get("response", ""),
            "speech_text": resposta.get("speech_text", resposta.get("response", "")),
            "actions": resposta.get("actions", []),
        }
    return {
        "query": payload.query,
        "response": resposta,
        "speech_text": resposta,
        "actions": [],
    }
