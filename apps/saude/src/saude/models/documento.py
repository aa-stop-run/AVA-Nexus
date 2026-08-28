import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class DocumentoSaude(Base):
    __tablename__ = "documento_saude"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    nome_ficheiro: Mapped[str] = mapped_column(String(255), nullable=False)
    caminho_ficheiro: Mapped[str] = mapped_column(String(500), nullable=False)
    tipo_mime: Mapped[str] = mapped_column(String(100), default="application/pdf", nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    data_documento: Mapped[date] = mapped_column(Date, nullable=False)
    laboratorio_clinica: Mapped[str | None] = mapped_column(String(150), nullable=True)
    paperless_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="documentos")
