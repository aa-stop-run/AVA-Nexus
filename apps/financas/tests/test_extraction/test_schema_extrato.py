from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ava.extraction.schema_extrato import MovimentoExtraido


def test_movimento_aceita_valor_dentro_do_limite_plausivel():
    movimento = MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("999999.99"), descricao="Teste")
    assert movimento.valor == Decimal("999999.99")


def test_movimento_rejeita_valor_acima_do_limite_plausivel():
    # Rede de segurança contra o mesmo erro de parsing que já aconteceu duas vezes no parser do
    # BPI (número de referência colado ao valor real por um regex demasiado permissivo) — sem
    # este limite, o valor implausível só é apanhado (por sorte) pelo NUMERIC(12,2) do Postgres
    # no momento do INSERT, em vez de ser rejeitado de forma explícita e imediata.
    with pytest.raises(ValidationError, match="implausível"):
        MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("1000000.01"), descricao="Teste")


def test_movimento_rejeita_valor_negativo_acima_do_limite_plausivel():
    with pytest.raises(ValidationError, match="implausível"):
        MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("-1000000.01"), descricao="Teste")
