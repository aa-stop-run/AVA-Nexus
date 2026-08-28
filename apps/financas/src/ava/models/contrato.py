import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class Contrato(Base):
    __tablename__ = "contrato"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    titular_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=False
    )
    ativo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ativo.id"), nullable=True
    )
    fornecedor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fornecedor.id"), nullable=True
    )
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    # seguro_auto | seguro_habitacao | seguro_saude | seguro_vida | telecomunicacoes | energia | garantia | subscricao | outro
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    numero_referencia: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    data_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    renovacao_automatica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dias_aviso_previo: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    valor: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # anual | mensal | trimestral | semestral | unica
    periodicidade: Mapped[str] = mapped_column(String(20), nullable=False, default="mensal")
    documento_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documento.id"), nullable=True
    )
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
