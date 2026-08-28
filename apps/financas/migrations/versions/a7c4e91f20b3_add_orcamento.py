"""add orcamento

O modelo `ava.models.orcamento` e o seu repositório/rotas foram escritos sem nunca ter existido
uma migração que criasse a tabela: numa base de dados nova a aplicação rebentava, e
`alembic check` acusava deriva permanente. Esta migração fecha esse buraco.

É defensiva por construção (`_tabela_existe`) porque a tabela JÁ existe nas bases de dados onde
foi criada à mão por `Base.metadata.create_all` ou por script — nesse caso só falta a constraint
de unicidade, que é aplicada na mesma.

Revision ID: a7c4e91f20b3
Revises: e1a2b3c4d5e6
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4e91f20b3"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "uq_orcamento_grupo_ano_mes"


def _tabela_existe(nome: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nome)


def _constraint_existe(tabela: str, nome: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == nome for c in inspector.get_unique_constraints(tabela))


def upgrade() -> None:
    if not _tabela_existe("orcamento"):
        op.create_table(
            "orcamento",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("grupo_categoria_id", sa.UUID(), nullable=False),
            sa.Column("ano", sa.Integer(), nullable=False),
            sa.Column("mes", sa.Integer(), nullable=False),
            sa.Column("limite_mensal", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.ForeignKeyConstraint(["grupo_categoria_id"], ["grupo_categoria.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if _constraint_existe("orcamento", _CONSTRAINT):
        return

    # Deduplicar ANTES de aplicar a constraint: numa base de dados que já usou a tabela, nada
    # impedia duas linhas para o mesmo (grupo, ano, mes) — criar_orcamento fazia INSERT cego e a
    # rota de gravação procurava o "existente" com um match não exato. Sem esta limpeza, o
    # ALTER TABLE abaixo falharia e deixaria a migração impossível de aplicar.
    # Mantém-se a linha de `ctid` mais alto (a gravada mais recentemente), que é a que reflete a
    # última intenção do utilizador.
    op.execute(
        """
        DELETE FROM orcamento a
        USING orcamento b
        WHERE a.grupo_categoria_id = b.grupo_categoria_id
          AND a.ano = b.ano
          AND a.mes = b.mes
          AND a.ctid < b.ctid
        """
    )
    op.create_unique_constraint(_CONSTRAINT, "orcamento", ["grupo_categoria_id", "ano", "mes"])


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "orcamento", type_="unique")
    op.drop_table("orcamento")
