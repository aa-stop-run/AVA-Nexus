import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class ConsultaMedica(Base):
    __tablename__ = "consulta_medica"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    data_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    especialidade: Mapped[str] = mapped_column(String(80), nullable=False)  # Pediatria, Oftalmologia, Dentista, Medicina Geral, etc.
    medico: Mapped[str | None] = mapped_column(String(120), nullable=True)
    local_clinica: Mapped[str | None] = mapped_column(String(150), nullable=True)  # CUF, Hospital da Luz, etc.
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    preparacao_instrucoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostico_notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    custo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    
    concluida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    codigo_confirmacao: Mapped[str | None] = mapped_column(String(60), nullable=True)
    documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Ligação ao Paperless

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="consultas")
