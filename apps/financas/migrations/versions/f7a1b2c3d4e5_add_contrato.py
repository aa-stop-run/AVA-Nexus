"""add contrato table for insurance, contracts and warranties

Revision ID: f7a1b2c3d4e5
Revises: e2f6b81c4a9d
Create Date: 2026-08-24 17:45:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e2f6b81c4a9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contrato",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("titular_id", sa.UUID(), nullable=False),
        sa.Column("ativo_id", sa.UUID(), nullable=True),
        sa.Column("fornecedor_id", sa.UUID(), nullable=True),
        sa.Column("nome", sa.String(length=150), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("numero_referencia", sa.String(length=100), nullable=True),
        sa.Column("data_inicio", sa.Date(), nullable=False),
        sa.Column("data_fim", sa.Date(), nullable=True),
        sa.Column("renovacao_automatica", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("dias_aviso_previo", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("valor", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("periodicidade", sa.String(length=20), server_default="mensal", nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["ativo_id"], ["ativo.id"], name="fk_contrato_ativo_id"),
        sa.ForeignKeyConstraint(["documento_id"], ["documento.id"], name="fk_contrato_documento_id"),
        sa.ForeignKeyConstraint(["fornecedor_id"], ["fornecedor.id"], name="fk_contrato_fornecedor_id"),
        sa.ForeignKeyConstraint(["titular_id"], ["titular.id"], name="fk_contrato_titular_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contrato_titular_id"), "contrato", ["titular_id"])
    op.create_index(op.f("ix_contrato_ativo_id"), "contrato", ["ativo_id"])
    op.create_index(op.f("ix_contrato_tipo"), "contrato", ["tipo"])
    op.create_index(op.f("ix_contrato_data_fim"), "contrato", ["data_fim"])


def downgrade() -> None:
    op.drop_index(op.f("ix_contrato_data_fim"), table_name="contrato")
    op.drop_index(op.f("ix_contrato_tipo"), table_name="contrato")
    op.drop_index(op.f("ix_contrato_ativo_id"), table_name="contrato")
    op.drop_index(op.f("ix_contrato_titular_id"), table_name="contrato")
    op.drop_table("contrato")
