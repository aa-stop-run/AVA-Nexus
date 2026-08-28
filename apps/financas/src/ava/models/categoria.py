import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ava.models.base import Base


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = (
        UniqueConstraint("grupo_id", "nome", name="uq_categoria_grupo_nome"),
        # A natureza válida depende do tipo, e a base de dados é que o garante. Sem esta
        # constraint uma categoria de receita podia ficar "fixa" por um POST mal formado ou por
        # uma migração futura distraída, e a margem passava a somar uma coluna que não existe.
        CheckConstraint(
            "(tipo = 'receita' AND natureza IN ('recorrente', 'extraordinario'))"
            " OR (tipo = 'despesa' AND natureza IN ('fixa', 'variavel', 'poupanca'))",
            name="ck_categoria_natureza",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grupo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grupo_categoria.id"), nullable=False
    )
    nome: Mapped[str] = mapped_column(String(60), nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # despesa | receita
    # receita: recorrente | extraordinario. despesa: fixa | variavel | poupanca.
    # É o eixo "isto é fiável / é compromisso?"; o eixo "que espécie de fluxo é isto?" sai dos
    # tipos das contas e vive em financas/natureza.py.
    natureza: Mapped[str] = mapped_column(String(15), nullable=False)
    # Contador associado à categoria: a linha de movimento carrega a quantidade nesta unidade.
    # É isto que substitui a tabela leitura_consumo.
    unidade_contador: Mapped[str | None] = mapped_column(String(10), nullable=True)  # kWh | m3
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
