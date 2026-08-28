from decimal import Decimal
from pydantic import BaseModel, Field

class ReciboVencimentoExtraido(BaseModel):
    cartao_refeicao: Decimal = Field(ge=0, description="O valor que foi pago em subsídio de alimentação/cartão refeição.", default=Decimal("0.00"))
    entidade_patronal: str = Field(description="O nome da empresa ou entidade empregadora.")
    mes_referencia: int = Field(ge=1, le=12, description="O mês a que este recibo se refere (1 a 12).")
    ano_referencia: int = Field(ge=2000, description="O ano a que este recibo se refere.")
