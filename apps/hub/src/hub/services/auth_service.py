import os
import hmac
import hashlib
import time
import secrets
from typing import Optional, Dict, Any

SECRET_KEY = os.getenv("AVA_SECRET_KEY", "ava_personal_assistant_salt_2026_stark_hud")
PIN_ADMIN = os.getenv("AVA_PIN_ADMIN", os.getenv("AVA_PIN_CODE", "1234"))
PIN_MEMBER = os.getenv("AVA_PIN_MEMBER", "5678")

UTILIZADORES: Dict[str, Dict[str, Any]] = {
    "alex": {
        "id": "alex",
        "nome": "aa-stop-run",
        "papel": "admin",
        "pin": PIN_ADMIN,
    },
    "sam": {
        "id": "sam",
        "nome": "Member",
        "papel": "membro",
        "pin": PIN_MEMBER,
    },
}


def _gerar_assinatura(payload: str) -> str:
    """Gera assinatura HMAC-SHA256 para o payload da sessão."""
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verificar_pin(pin_candidato: str) -> Optional[Dict[str, Any]]:
    """
    Verifica se o PIN introduzido coincide com o do aa-stop-run (1234) ou da Member (5678).
    Retorna o perfil do utilizador correspondente ou None se inválido.
    """
    if not pin_candidato:
        return None
    pin_limpo = pin_candidato.strip()

    if hmac.compare_digest(pin_limpo, PIN_ADMIN):
        return {
            "id": "alex",
            "nome": "aa-stop-run",
            "papel": "admin",
        }

    if hmac.compare_digest(pin_limpo, PIN_MEMBER):
        return {
            "id": "sam",
            "nome": "Member",
            "papel": "membro",
        }

    return None


def obter_utilizador_por_id(user_id: str) -> Dict[str, Any]:
    """Retorna os dados do utilizador a partir do seu identificador (alex ou sam)."""
    if user_id == "sam":
        return {
            "id": "sam",
            "nome": "Member",
            "papel": "membro",
        }
    return {
        "id": "alex",
        "nome": "aa-stop-run",
        "papel": "admin",
    }


def criar_token_sessao(user_id: str = "alex", duracao_dias: int = 30) -> str:
    """Gera um token de sessão assinado e seguro válido por N dias para o utilizador."""
    expira_em = int(time.time()) + (duracao_dias * 24 * 3600)
    nonce = secrets.token_hex(8)
    payload = f"{user_id}:{expira_em}:{nonce}"
    sig = _gerar_assinatura(payload)
    return f"{payload}:{sig}"


def validar_token_sessao(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Valida a autenticidade e validade temporal do token de sessão.
    Retorna o perfil do utilizador ou None se o token for inválido ou expirado.
    """
    if not token or ":" not in token:
        return None

    partes = token.split(":")
    if len(partes) != 4:
        return None

    user_id, exp_str, nonce, sig = partes
    payload = f"{user_id}:{exp_str}:{nonce}"
    sig_esperada = _gerar_assinatura(payload)

    if not hmac.compare_digest(sig, sig_esperada):
        return None

    try:
        expira_em = int(exp_str)
        if time.time() > expira_em:
            return None
    except ValueError:
        return None

    if user_id == "ava_user":
        user_id = "alex"

    return obter_utilizador_por_id(user_id)

