import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class ExameMedico(Base):
    __tablename__ = "exame_medico"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    data: Mapped[date] = mapped_column(Date, nullable=False)
    tipo_exame: Mapped[str] = mapped_column(String(100), nullable=False)  # Análises de Sangue, Ecografia, etc.
    laboratorio_clinica: Mapped[str | None] = mapped_column(String(150), nullable=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    resultados_resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="exames")
