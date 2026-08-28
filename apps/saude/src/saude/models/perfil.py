import uuid
from datetime import date, datetime, timezone
from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class PerfilSaude(Base):
    __tablename__ = "perfil_saude"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titular_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("titular.id"), nullable=False, unique=True
    )
    
    numero_utente_sns: Mapped[str | None] = mapped_column(String(30), nullable=True)
    data_nascimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    grupo_sanguineo: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ex.: A+, A-, B+, B-, AB+, AB-, O+, O-
    alergias: Mapped[str | None] = mapped_column(Text, nullable=True)
    condicoes_cronicas: Mapped[str | None] = mapped_column(Text, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    titular = relationship("Titular", back_populates="perfil_saude")
    consultas = relationship("ConsultaMedica", back_populates="perfil", cascade="all, delete-orphan")
    exames = relationship("ExameMedico", back_populates="perfil", cascade="all, delete-orphan")
    medicamentos = relationship("MedicamentoAtivo", back_populates="perfil", cascade="all, delete-orphan")
    vacinas = relationship("VacinaRegisto", back_populates="perfil", cascade="all, delete-orphan")
    biomarcadores = relationship(
        "BiomarcadorLeitura",
        back_populates="perfil",
        cascade="all, delete-orphan",
        order_by="desc(BiomarcadorLeitura.data)",
    )
    documentos = relationship(
        "DocumentoSaude",
        back_populates="perfil",
        cascade="all, delete-orphan",
        order_by="desc(DocumentoSaude.data_documento)",
    )

    @property
    def total_medicamentos_ativos(self) -> int:
        return len([m for m in self.medicamentos if m.ativo])
