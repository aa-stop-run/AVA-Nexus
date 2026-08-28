"""add meta_poupanca table

Revision ID: a1b2c3d4e5f6
Revises: f7a1b2c3d4e5
Create Date: 2026-08-25 12:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_poupanca",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=True),
        sa.Column("valor_alvo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "valor_atual",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("data_alvo", sa.Date(), nullable=True),
        sa.Column("conta_id", sa.UUID(), nullable=True),
        sa.Column(
            "ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "ordem", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["conta_id"], ["conta.id"], name="fk_meta_poupanca_conta_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meta_poupanca_conta_id"), "meta_poupanca", ["conta_id"]
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_meta_poupanca_conta_id"), table_name="meta_poupanca"
    )
    op.drop_table("meta_poupanca")
