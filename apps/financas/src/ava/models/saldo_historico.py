import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class SaldoHistorico(Base):
    __tablename__ = "saldo_historico"
    __table_args__ = (UniqueConstraint("conta_id", "data", name="uq_saldo_conta_data"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conta_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conta.id"), nullable=False)
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Quem declarou este saldo: "extrato" (o banco, via extratos.py) ou "manual" (o utilizador,
    # em /configuracoes/patrimonio). São as DUAS únicas fontes — uma âncora nunca é calculada a
    # partir dos movimentos nem alterada depois de gravada (spec 2026-08-08, §7).
    origem: Mapped[str] = mapped_column(String(10), nullable=False, server_default="extrato")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
