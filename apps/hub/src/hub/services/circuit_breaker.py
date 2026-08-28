import time
import logging
import httpx
from typing import Any, Dict, Optional

logger = logging.getLogger("hub.circuit_breaker")


class CircuitState:
    CLOSED = "CLOSED"      # Normal: todas as chamadas são permitidas
    OPEN = "OPEN"          # Desligado/Falha: chamadas rejeitadas imediatamente (Fast Fail)
    HALF_OPEN = "HALF_OPEN"# Tentativa de recuperação


class OllamaCircuitBreaker:
    """
    Circuit Breaker para chamadas ao servidor Ollama na rede local (ex: localhost:11434).
    Previne que a AVA bloqueie ou sofra lentidão se o computador estiver desligado ou indisponível.
    """

    def __init__(
        self,
        failure_threshold: int = 2,
        recovery_timeout: float = 60.0,
        request_timeout: float = 2.5,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.request_timeout = request_timeout

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_success_time = 0.0

    @property
    def is_open(self) -> bool:
        """Verifica se o circuito está aberto (servidor indisponível)."""
        if self.state == CircuitState.OPEN:
            agora = time.time()
            if agora - self.last_failure_time >= self.recovery_timeout:
                logger.info("Circuit Breaker a tentar reestabelecer ligação com Ollama (HALF_OPEN)...")
                self.state = CircuitState.HALF_OPEN
                return False
            return True
        return False

    def record_success(self):
        """Regista chamada bem-sucedida e normaliza o circuito."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_success_time = time.time()

    def record_failure(self, erro: str):
        """Regista falha e abre o circuito se atingir o limiar."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(
            "Falha ao contactar Ollama (%d/%d): %s",
            self.failure_count,
            self.failure_threshold,
            erro,
        )
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(
                "Ollama indisponível. Circuit Breaker ATIVADO (OPEN) por %.0fs. "
                "AVA a operar em Modo Autónomo Local.",
                self.recovery_timeout,
            )

    async def execute_generate(
        self,
        base_url: str,
        model: str,
        prompt: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Executa chamada a /api/generate no Ollama protegido pelo Circuit Breaker.
        Devolve o texto gerado ou None caso o servidor esteja inacessível.
        """
        if self.is_open:
            logger.debug("Ollama ignorado pelo Circuit Breaker (servidor em pausa).")
            return None

        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options or {"temperature": 0.3, "num_predict": 256},
        }

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    self.record_success()
                    data = resp.json()
                    return data.get("response", "").strip()
                else:
                    self.record_failure(f"HTTP {resp.status_code}")
                    return None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            self.record_failure(f"Timeout/Conexão: {type(e).__name__}")
            return None
        except Exception as e:
            self.record_failure(f"Erro inesperado: {e}")
            return None


# Instância global do Circuit Breaker para o Ollama
ollama_circuit_breaker = OllamaCircuitBreaker()
