import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from casa.models.base import Base


class EquipamentoCasa(Base):
    __tablename__ = "equipamento_casa"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(80), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    categoria: Mapped[str] = mapped_column(String(50), nullable=False, default="eletronica")  # eletronica, eletrodomestico, climatizacao, audio_video, etc.
    divisao_casa: Mapped[str] = mapped_column(String(60), nullable=False, default="Geral")    # Sala, Cozinha, Quarto Casal, Quarto Junior, Escritorio, etc.
    
    data_compra: Mapped[date | None] = mapped_column(Date, nullable=True)
    valor_compra: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fornecedor_loja: Mapped[str | None] = mapped_column(String(100), nullable=True)           # PCDIGA, Worten, FNAC, etc.
    
    anos_garantia: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    data_fim_garantia: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    paperless_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numero_fatura: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    manutencoes = relationship("ManutencaoCasa", back_populates="equipamento", cascade="all, delete-orphan")

    @property
    def dias_restantes_garantia(self) -> int | None:
        if not self.data_fim_garantia:
            return None
        hoje = date.today()
        return (self.data_fim_garantia - hoje).days

    @property
    def estado_garantia(self) -> str:
        """em_garantia (>30 dias), a_expirar (<=30 dias), expirada (<0 dias), s_garantia"""
        d = self.dias_restantes_garantia
        if d is None:
            return "s_garantia"
        if d < 0:
            return "expirada"
        if d <= 30:
            return "a_expirar"
        return "em_garantia"
