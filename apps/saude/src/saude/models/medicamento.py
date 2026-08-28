import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saude.models.base import Base


class MedicamentoAtivo(Base):
    __tablename__ = "medicamento_ativo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    perfil_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("perfil_saude.id"), nullable=False
    )

    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    dosagem: Mapped[str | None] = mapped_column(String(60), nullable=True)  # ex.: 500mg, 10mg
    posologia: Mapped[str | None] = mapped_column(String(150), nullable=True)  # ex.: 1 comp. de 12 em 12h
    data_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    perfil = relationship("PerfilSaude", back_populates="medicamentos")


class Medicamento(Base):
    __tablename__ = "medicamento"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    titular: Mapped[str] = mapped_column(String(50), nullable=False)  # 'aa-stop-run', 'Member', 'Junior'
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    principio_ativo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dosagem: Mapped[str] = mapped_column(String(50), nullable=False)
    forma_farmaceutica: Mapped[str] = mapped_column(String(50), default="pill")
    stock_atual: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock_minimo_alerta: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    unidade_medida: Mapped[str] = mapped_column(String(20), default="unidades")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    instrucoes_toma: Mapped[str | None] = mapped_column(Text, nullable=True)
    medico_prescritor: Mapped[str | None] = mapped_column(String(100), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    horarios = relationship("MedicamentoTomaHorario", back_populates="medicamento", cascade="all, delete-orphan", lazy="selectin")
    registos_toma = relationship("MedicamentoRegistoToma", back_populates="medicamento", cascade="all, delete-orphan", lazy="selectin")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "ativo" not in kwargs:
            self.ativo = True
        if "forma_farmaceutica" not in kwargs:
            self.forma_farmaceutica = "pill"
        if "unidade_medida" not in kwargs:
            self.unidade_medida = "unidades"
        if "stock_atual" not in kwargs:
            self.stock_atual = 0
        if "stock_minimo_alerta" not in kwargs:
            self.stock_minimo_alerta = 7


class MedicamentoTomaHorario(Base):
    __tablename__ = "medicamento_toma_horario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    medicamento_id: Mapped[int] = mapped_column(ForeignKey("medicamento.id", ondelete="CASCADE"), nullable=False)
    hora: Mapped[str] = mapped_column(String(5), nullable=False)  # '08:30'
    quantidade_dose: Mapped[float] = mapped_column(Numeric(4, 2), default=1.0, nullable=False)
    dias_semana: Mapped[str] = mapped_column(String(50), default="todos", nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    medicamento = relationship("Medicamento", back_populates="horarios")


class MedicamentoRegistoToma(Base):
    __tablename__ = "medicamento_registo_toma"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    medicamento_id: Mapped[int] = mapped_column(ForeignKey("medicamento.id", ondelete="CASCADE"), nullable=False)
    data_hora_prevista: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_hora_tomada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="tomado", nullable=False)  # 'tomado', 'adiado', 'ignorado'
    registado_via: Mapped[str] = mapped_column(String(30), default="mobile_notification", nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    medicamento = relationship("Medicamento", back_populates="registos_toma")
