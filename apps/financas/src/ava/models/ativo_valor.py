import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ava.models.base import Base


class AtivoValor(Base):
    """Uma avaliação OBSERVADA de um ativo numa data. Espelha saldo_historico.

    Só entram aqui valores que alguém viu: uma fatura de compra, um anúncio equivalente, uma
    avaliação. O valor projetado pela depreciação (ava.financas.valorizacao) nunca é gravado —
    é sempre calculado na leitura, para uma estimativa nunca poder endurecer em facto.
    """

    __tablename__ = "ativo_valor"
    # Duas avaliações do mesmo bem no mesmo dia são uma correção, não dois factos.
    __table_args__ = (UniqueConstraint("ativo_id", "data", name="uq_ativo_valor_ativo_data"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ativo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ativo.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # origem: observado | aquisicao. "aquisicao" é o valor de compra — não altera nenhum
    # cálculo, existe para a página de detalhe o poder rotular.
    origem: Mapped[str] = mapped_column(String(12), nullable=False, default="observado")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
