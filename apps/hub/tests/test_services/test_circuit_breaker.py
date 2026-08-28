import pytest
import time
from hub.services.circuit_breaker import OllamaCircuitBreaker, CircuitState


def test_circuit_breaker_initial_state():
    cb = OllamaCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    assert cb.state == CircuitState.CLOSED
    assert not cb.is_open
    assert cb.failure_count == 0


def test_circuit_breaker_trips_on_failures():
    cb = OllamaCircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    
    cb.record_failure("Erro 1")
    assert cb.state == CircuitState.CLOSED
    assert not cb.is_open

    cb.record_failure("Erro 2")
    assert cb.state == CircuitState.OPEN
    assert cb.is_open


def test_circuit_breaker_recovers_after_timeout():
    cb = OllamaCircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
    cb.record_failure("Timeout")
    assert cb.state == CircuitState.OPEN
    assert cb.is_open

    # Esperar recuperação
    time.sleep(0.15)
    # Ao verificar is_open após o timeout, deve mudar para HALF_OPEN
    assert not cb.is_open
    assert cb.state == CircuitState.HALF_OPEN

    # Sucesso normaliza para CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
