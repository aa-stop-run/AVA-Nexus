import json
import logging
import os

import httpx

llm_logger = logging.getLogger("ava.llm_client")


class LLMClient:
    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120.0)

    async def chat_completion_json(
        self, system_prompt: str, user_prompt: str, schema: dict | None = None
    ) -> dict:
        """Faz a chamada e garante (na medida do possível) que devolve dict válido."""
        llm_logger.info("Chamando LLM com system prompt len=%d, user prompt len=%d", len(system_prompt), len(user_prompt))
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "extracao",
                    "schema": schema
                }
            }
            
        response = await self._client.post(
            "/v1/chat/completions",
            json=payload,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload["choices"][0]["message"]
        conteudo = message.get("content")
        
        # Llama 3.1 sometimes outputs tool_calls instead of content
        if not conteudo and "tool_calls" in message and message["tool_calls"]:
            tool_call = message["tool_calls"][0]
            if "function" in tool_call and "arguments" in tool_call["function"]:
                return json.loads(tool_call["function"]["arguments"])
                
        if not conteudo:
            return {}
            
        if conteudo.startswith("```json"):
            conteudo = conteudo[7:]
        if conteudo.startswith("```"):
            conteudo = conteudo[3:]
        if conteudo.endswith("```"):
            conteudo = conteudo[:-3]
        conteudo = conteudo.strip()

        parsed = None
        try:
            parsed = json.loads(conteudo)
        except json.JSONDecodeError:
            # If JSON decode fails, let's try to extract JSON from markdown explicitly
            import re
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', conteudo, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    llm_logger.error("Falha ao extrair JSON do markdown: %r", conteudo)
            else:
                llm_logger.error("JSON inválido (sem markdown): %r", conteudo)
                    
        if parsed is None:
            llm_logger.error("Parsed is None para conteudo: %r", conteudo)
            return {}
            
        if isinstance(parsed, dict):
            # Check for tool call wrappers
            if "name" in parsed:
                args = parsed.get("arguments") or parsed.get("parameters")
                if args is not None:
                    if isinstance(args, str):
                        try:
                            return json.loads(args)
                        except json.JSONDecodeError:
                            return {}
                    return args
            
            # Check for JSON schema wrapper
            if "properties" in parsed:
                return parsed["properties"]
                
        return parsed

    async def aclose(self) -> None:
        await self._client.aclose()
