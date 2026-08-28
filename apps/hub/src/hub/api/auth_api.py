from fastapi import APIRouter, Request, Response, HTTPException, status
from pydantic import BaseModel
from hub.services.auth_service import verificar_pin, criar_token_sessao, validar_token_sessao

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NOME = "ava_session_token"
MAX_AGE_SEGUNDOS = 30 * 24 * 3600  # 30 dias


class PinPayload(BaseModel):
    pin: str


@router.post("/pin")
async def login_com_pin(payload: PinPayload, response: Response):
    """Valida o código PIN (1234 para aa-stop-run ou 5678 para Member) e emite cookie de sessão seguro por 30 dias."""
    user = verificar_pin(payload.pin)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código PIN incorreto. Tenta novamente.",
        )

    token = criar_token_sessao(user_id=user["id"], duracao_dias=30)
    response.set_cookie(
        key=COOKIE_NOME,
        value=token,
        max_age=MAX_AGE_SEGUNDOS,
        httponly=True,
        samesite="lax",
        secure=False,  # Em rede local Tailscale HTTP
        path="/",
    )
    return {
        "status": "ok",
        "authenticated": True,
        "user": user,
        "message": f"Bem-vindo(a) ao Cockpit AVA, {user['nome']}!",
    }


@router.post("/logout")
async def logout_cockpit(response: Response):
    """Tranca o Cockpit da AVA e revoga o cookie de sessão."""
    response.delete_cookie(key=COOKIE_NOME, path="/")
    return {
        "status": "ok",
        "authenticated": False,
        "message": "Cockpit trancado com sucesso.",
    }


@router.get("/status")
async def verificar_estado_sessao(request: Request):
    """Verifica se o cliente atual possui uma sessão autenticada válida."""
    token = request.cookies.get(COOKIE_NOME)
    user = validar_token_sessao(token)
    return {
        "authenticated": user is not None,
        "user": user,
    }
