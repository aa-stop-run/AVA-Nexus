import uuid
from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Titular(Base):
    __tablename__ = "titular"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # proprio | conjuge | filho
    data_nascimento: Mapped[date | None] = mapped_column(Date, nullable=True)
