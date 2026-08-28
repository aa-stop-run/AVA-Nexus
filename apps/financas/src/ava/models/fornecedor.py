import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Fornecedor(Base):
    __tablename__ = "fornecedor"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    nif: Mapped[str | None] = mapped_column(String(9), nullable=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)  # eletricidade | agua | telecom | seguradora | outro
    tem_parser_nivel0: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
