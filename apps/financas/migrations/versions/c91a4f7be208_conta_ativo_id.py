"""conta.ativo_id: liga uma divida ao bem que financiou

Ver docs/superpowers/specs/2026-08-07-divida-ligada-ao-bem-design.md §2.

Revision ID: c91a4f7be208
Revises: d40c7b81e5a3
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c91a4f7be208"
down_revision: Union[str, Sequence[str], None] = "d40c7b81e5a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coluna_existe(tabela: str, coluna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == coluna for c in inspector.get_columns(tabela))


def upgrade() -> None:
    if not _coluna_existe("conta", "ativo_id"):
        op.add_column("conta", sa.Column("ativo_id", sa.UUID(), nullable=True))
        op.create_foreign_key("fk_conta_ativo_id", "conta", "ativo", ["ativo_id"], ["id"])


def downgrade() -> None:
    if _coluna_existe("conta", "ativo_id"):
        op.drop_constraint("fk_conta_ativo_id", "conta", type_="foreignkey")
        op.drop_column("conta", "ativo_id")
