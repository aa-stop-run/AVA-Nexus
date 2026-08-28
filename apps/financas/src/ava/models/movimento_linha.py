import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ava.models.base import Base

if TYPE_CHECKING:
    from ava.models.categoria import Categoria
    from ava.models.movimento import Movimento


class MovimentoLinha(Base):
    """Para o que foi um movimento. Um movimento simples tem uma linha; um dividido tem várias.

    A categoria vive aqui, nunca no movimento — ver a spec §3.2. Sem isso, cada consulta de
    análise teria de decidir "se tem linhas usa linhas, senão usa o movimento", que é a classe
    de condicional espalhada que já causou defeitos neste código.
    """

    __tablename__ = "movimento_linha"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    movimento_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movimento.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL = por categorizar, ou transferência (que nunca leva categoria). Distinguem-se por
    # movimento.tipo, ver spec §3.2.
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=True
    )
    categoria: Mapped["Categoria | None"] = relationship()
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Contador na unidade declarada pela categoria (ex. 312.000 kWh). Substitui leitura_consumo.
    quantidade: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    unidade: Mapped[str | None] = mapped_column(String(10), nullable=True)
    
    ativo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ativo.id"), nullable=True
    )
    conta_relacionada_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conta.id"), nullable=True
    )
    ressarcimento_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ressarcimento.id"), nullable=True, index=True
    )
    from sqlalchemy import Integer
    leitura_odometro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    movimento: Mapped["Movimento"] = relationship(back_populates="linhas")

