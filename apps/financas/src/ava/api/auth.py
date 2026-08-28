from fastapi import Depends, Header, HTTPException, status

from ava.config import Settings, get_settings


async def verificar_token_worker(
    authorization: str = Header(...), settings: Settings = Depends(get_settings)
) -> None:
    esperado = f"Bearer {settings.worker_shared_token}"
    if authorization != esperado:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token inválido")
