from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

# Rede de segurança contra erros de parsing que produzem valores absurdos (ex.: um número de
# referência/apólice colado ao valor real por um regex demasiado permissivo — já aconteceu duas
# vezes neste projeto com o parser do BPI, ambas descobertas só porque a coluna NUMERIC(12,2) do
# Postgres rejeitou o INSERT, não por nenhuma validação do próprio parser). Um milhão de euros é
# generoso o suficiente para nunca rejeitar um movimento familiar real, mas suficientemente
# apertado para apanhar valores de várias ordens de grandeza a mais causados por um parse errado.
VALOR_MOVIMENTO_MAXIMO_PLAUSIVEL = Decimal("1000000")


class SaldoFinal(BaseModel):
    data: date
    valor: Decimal


class MovimentoExtraido(BaseModel):
    data: date
    valor: Decimal  # sinal: + entrada, − saída
    descricao: str

    @field_validator("valor")
    @classmethod
    def _valor_dentro_do_limite_plausivel(cls, valor: Decimal) -> Decimal:
        if abs(valor) > VALOR_MOVIMENTO_MAXIMO_PLAUSIVEL:
            raise ValueError(f"valor de movimento implausível: {valor}")
        return valor


class ExtratoBancario(BaseModel):
    instituicao: str
    tipo_conta: str
    nome_conta: str
    saldo_final: SaldoFinal
    # Necessário para o checksum de §7 da spec: saldo_final − saldo_inicial == Σ(movimentos).
    # O caminho nível-1 (LLM) também o recebe no schema do prompt e portanto pode devolvê-lo;
    # se vier None, o extrato não é verificável e vai para revisão manual em vez de se confiar nele.
    saldo_inicial: Decimal | None = None
    movimentos: list[MovimentoExtraido] = Field(default_factory=list)
    # Contagem de linhas de movimento que bateram na forma esperada mas foram descartadas por
    # não serem convertíveis (data/valor garbled) — sinal estrutural de A-P6 (falha nunca
    # silenciosa) para quem consome o extrato a jusante. Só o parser de regex (banco_generico.py)
    # consegue saber este número; o caminho nível-1 (LLM, worker/nivel_extrato.py) não tem como
    # detetar "linhas que existiam mas não reconheceu", por isso o default 0 mantém esse
    # caminho válido sem forçar o LLM a inventar um valor.
    linhas_nao_reconhecidas: int = 0
