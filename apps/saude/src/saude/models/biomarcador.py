import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class BiomarcadorLeitura(Base):
    __tablename__ = "biomarcador_leitura"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    data: Mapped[date] = mapped_column(Date, nullable=False)
    categoria: Mapped[str] = mapped_column(String(50), nullable=False, default="Geral")
    parametro: Mapped[str] = mapped_column(String(80), nullable=False)  # ex.: Glicemia, Colesterol LDL, etc.
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unidade: Mapped[str] = mapped_column(String(20), nullable=False, default="mg/dL")
    
    valor_referencia_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    valor_referencia_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    
    laboratorio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="biomarcadores")

    @property
    def estado(self) -> str:
        """Calcula se o valor está 'normal', 'alto' ou 'baixo'."""
        if self.valor_referencia_max is not None and self.valor > self.valor_referencia_max:
            return "alto"
        if self.valor_referencia_min is not None and self.valor < self.valor_referencia_min:
            return "baixo"
        return "normal"
