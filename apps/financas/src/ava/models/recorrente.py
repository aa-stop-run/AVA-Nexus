import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Recorrente(Base):
    """Movimento esperado todos os meses. Generaliza rendimento_recorrente para servir também
    saídas (renda, prestações, subscrições), o que é o que permite comparar esperado vs. real."""

    __tablename__ = "recorrente"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(15), nullable=False)  # entrada | saida
    categoria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=False
    )
    conta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conta.id"), nullable=True
    )
    titular_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=False
    )
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    dia_do_mes: Mapped[int] = mapped_column(Integer, nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
