import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class VacinaRegisto(Base):
    __tablename__ = "vacina_registo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    nome_vacina: Mapped[str] = mapped_column(String(120), nullable=False)  # ex.: Tétano, Gripe, Meningite B
    data_toma: Mapped[date] = mapped_column(Date, nullable=False)
    proxima_dose_data: Mapped[date | None] = mapped_column(Date, nullable=True)
    lote_local: Mapped[str | None] = mapped_column(String(120), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="vacinas")
