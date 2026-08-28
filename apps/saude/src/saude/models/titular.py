import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class Titular(Base):
    __tablename__ = "titular"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(50), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="proprio")  # proprio, conjuge, filho, dependente

    perfil_saude = relationship("PerfilSaude", back_populates="titular", uselist=False, cascade="all, delete-orphan")
