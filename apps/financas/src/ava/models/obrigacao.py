import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class Obrigacao(Base):
    __tablename__ = "obrigacao"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=True
    )
    # nullable: obrigações criadas por outras vias (ex. futura extracao/manual origem) podem não
    # ter um ativo associado — só as geradas por sincronizar_obrigacoes_ativo (origem="regra")
    # o preenchem. Existe para desambiguar duas obrigações do mesmo tipo/data/titular quando um
    # agregado tem vários ativos (ver dedupe em obrigacao_repo.existe_obrigacao).
    ativo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ativo.id"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    data_limite: Mapped[date] = mapped_column(Date, nullable=False)
    origem: Mapped[str] = mapped_column(String(20), nullable=False)  # extracao | regra | manual
    documento_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documento.id"), nullable=True
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
