import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from cidadania.models.base import Base


class ObrigacaoFiscal(Base):
    __tablename__ = "obrigacao_fiscal"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(140), nullable=False)
    categoria: Mapped[str] = mapped_column(String(50), nullable=False)  # efatura, irs, imi, iuc, outro
    ano_fiscal: Mapped[int] = mapped_column(Integer, nullable=False, default=2026)
    
    data_limite: Mapped[date] = mapped_column(Date, nullable=False)
    valor_estimado: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    pago: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_pagamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    detalhes: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    @property
    def dias_restantes(self) -> int:
        hoje = date.today()
        return (self.data_limite - hoje).days

    @property
    def estado(self) -> str:
        if self.pago:
            return "concluido"
        d = self.dias_restantes
        if d < 0:
            return "em_falta"
        if d <= 15:
            return "urgente"
        return "pendente"
