import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class Documento(Base):
    __tablename__ = "documento"
    __table_args__ = (UniqueConstraint("paperless_document_id", name="uq_documento_paperless_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paperless_document_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fornecedor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fornecedor.id"), nullable=True
    )
    nivel_extracao: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_validacao: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")
    dados_extraidos: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # O que a ingestão deste documento produziu, por secção de conta:
    # {"contas": [{"conta": str, "criadas": int, "saltadas": int}]}.
    #
    # Coluna PRÓPRIA e não uma chave dentro de `dados_extraidos`: esse campo é validado como
    # ExtratoBancario (e testado com `isinstance(dados.get("contas"), list)`) em
    # _aprovar_extrato_manualmente, e uma chave a mais lá dentro é uma chave a mais no caminho
    # de validação.
    resumo_ingestao: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    registado_por: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=True
    )
    ambito: Mapped[str] = mapped_column(String(10), nullable=False, default="comum")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
