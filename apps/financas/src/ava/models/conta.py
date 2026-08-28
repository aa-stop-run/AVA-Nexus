import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Conta(Base):
    __tablename__ = "conta"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=False
    )
    instituicao: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # tipo: a_ordem | poupanca | investimento | certificados | divida | cartao_refeicao
    categoria_divida: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # categoria_divida (só relevante quando tipo == "divida"):
    # habitacao | pessoal | automovel | cartao | obras | consolidado | outro
    categoria_investimento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # categoria_investimento (só relevante quando tipo == "investimento"):
    # ppr | etf | acoes | obrigacoes | outro
    # O bem que esta dívida financiou (hipoteca -> casa, crédito automóvel -> carro). NULL é o
    # caso normal: contas à ordem, cartões e créditos pessoais não pertencem a bem nenhum.
    # N:1 — um bem pode ter várias dívidas, uma dívida pertence quando muito a um bem.
    ativo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ativo.id"), nullable=True
    )
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
