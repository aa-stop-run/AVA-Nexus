import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Orcamento(Base):
    """Limite de despesa definido para um grupo de categorias num mês concreto."""

    __tablename__ = "orcamento"
    # Um grupo só pode ter UM limite por mês. Sem esta constraint, gravar o mesmo orçamento duas
    # vezes (duplo submit do formulário, ou uma correção feita por script) deixa duas linhas para
    # o mesmo (grupo, ano, mes) e a comparação orçado-vs-real passa a depender de qual delas a
    # query apanha primeiro — silenciosamente, sem erro.
    __table_args__ = (
        UniqueConstraint("grupo_categoria_id", "ano", "mes", name="uq_orcamento_grupo_ano_mes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grupo_categoria_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grupo_categoria.id"), nullable=False
    )
    ano: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    limite_mensal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
