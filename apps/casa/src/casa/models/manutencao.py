import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from casa.models.base import Base


class ManutencaoCasa(Base):
    __tablename__ = "manutencao_casa"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    equipamento_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipamento_casa.id"), nullable=True
    )
    
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)  # Revisão Caldeira, Limpeza Filtros AC, etc.
    divisao_casa: Mapped[str] = mapped_column(String(60), nullable=False, default="Geral")
    periodicidade_meses: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    
    ultima_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    proxima_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    custo_estimado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tecnico_contacto: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    concluida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    equipamento = relationship("EquipamentoCasa", back_populates="manutencoes")

    @property
    def dias_restantes(self) -> int | None:
        if not self.proxima_data:
            return None
        hoje = date.today()
        return (self.proxima_data - hoje).days
