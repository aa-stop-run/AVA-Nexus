from fastapi import Request

from ava.integrations.paperless import PaperlessClient


async def get_paperless_client(request: Request) -> PaperlessClient:
    return request.app.state.paperless_client
