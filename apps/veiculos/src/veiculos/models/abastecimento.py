import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from veiculos.models.base import Base


class VeiculoAbastecimento(Base):
    __tablename__ = "veiculo_abastecimento"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    veiculo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("veiculo.id"), nullable=False)
    
    data: Mapped[date] = mapped_column(Date, nullable=False)
    km: Mapped[int] = mapped_column(Integer, nullable=False)
    quantidade: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)  # Litros ou kWh
    preco_total: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    preco_unitario: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    
    posto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tanque_cheio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    veiculo = relationship("Veiculo", back_populates="abastecimentos")
