import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from veiculos.models.base import Base


class VeiculoManutencao(Base):
    __tablename__ = "veiculo_manutencao"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    veiculo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("veiculo.id"), nullable=False)
    
    data: Mapped[date] = mapped_column(Date, nullable=False)
    km: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_servico: Mapped[str] = mapped_column(String(40), nullable=False, default="revisao_geral")
    # revisao_geral, oleo_filtros, pneus, travoes, bateria, correia, ipo, avaria, outro
    
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    oficina: Mapped[str | None] = mapped_column(String(120), nullable=True)
    custo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    
    proxima_revisao_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxima_revisao_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    documento_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    veiculo = relationship("Veiculo", back_populates="manutencoes")
