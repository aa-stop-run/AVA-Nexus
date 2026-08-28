import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from veiculos.models.base import Base


class Veiculo(Base):
    __tablename__ = "veiculo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ativo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="carro")  # carro, mota, comercial
    matricula: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ano_matricula: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mes_matricula: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combustivel: Mapped[str] = mapped_column(String(20), nullable=False, default="gasoleo")  # gasoleo, gasolina, eletrico, hibrido
    
    km_atual: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_ultima_ipo: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_proxima_ipo: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    seguradora: Mapped[str | None] = mapped_column(String(100), nullable=True)
    numero_apolice: Mapped[str | None] = mapped_column(String(60), nullable=True)
    data_fim_seguro: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    manutencoes = relationship("VeiculoManutencao", back_populates="veiculo", cascade="all, delete-orphan")
    abastecimentos = relationship("VeiculoAbastecimento", back_populates="veiculo", cascade="all, delete-orphan")
