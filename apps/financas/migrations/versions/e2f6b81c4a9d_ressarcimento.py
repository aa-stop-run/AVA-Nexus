"""ressarcimento: o grupo que liga um reembolso a despesa

Revision ID: e2f6b81c4a9d
Revises: c4a7e2f81b6d
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f6b81c4a9d"
down_revision: Union[str, Sequence[str], None] = "c4a7e2f81b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ressarcimento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Nulável e sem backfill: nenhuma linha existente pode estar ligada a um grupo que ainda não
    # existia antes desta migração.
    op.add_column(
        "movimento_linha", sa.Column("ressarcimento_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_movimento_linha_ressarcimento", "movimento_linha", "ressarcimento",
        ["ressarcimento_id"], ["id"],
    )
    op.create_index(
        op.f("ix_movimento_linha_ressarcimento_id"), "movimento_linha", ["ressarcimento_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_movimento_linha_ressarcimento_id"), table_name="movimento_linha")
    op.drop_constraint("fk_movimento_linha_ressarcimento", "movimento_linha", type_="foreignkey")
    op.drop_column("movimento_linha", "ressarcimento_id")
    op.drop_table("ressarcimento")
