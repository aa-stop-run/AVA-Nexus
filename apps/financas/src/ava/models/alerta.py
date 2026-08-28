import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class Alerta(Base):
    __tablename__ = "alerta"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # idade_fila | falha_ingestao
    chave_deduplicacao: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    enviado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
