import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class DivergenciaAceite(Base):
    """Uma divergência que o utilizador decidiu não perseguir.

    É o ÚNICO estado guardado da reconciliação: a lista de divergências é calculada a cada
    pedido, para se curar sozinha quando o movimento em falta for classificado (spec §10). Sem
    esta tabela, uma divergência que nunca vai ser resolvida — um extrato perdido — ficaria a
    incomodar para sempre.
    """

    __tablename__ = "divergencia_aceite"
    __table_args__ = (
        UniqueConstraint("conta_id", "data", name="uq_divergencia_conta_data"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conta_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conta.id"), nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    motivo: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
