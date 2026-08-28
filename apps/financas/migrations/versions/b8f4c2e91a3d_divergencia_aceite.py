"""divergencia_aceite: dispensas de reconciliacao

Ver docs/superpowers/specs/2026-08-08-saldo-derivado-design.md §10-11: a lista de divergências em
/reconciliacao é CALCULADA a cada pedido, nunca escrita — só a decisão de não a perseguir precisa
de ficar gravada. Esta tabela é esse único estado.

Defensiva por construção (`_tabela_existe`), no mesmo padrão de a7c4e91f20b3 (add_orcamento) e
940d9b761f7e (saldo_historico.origem).

Revision ID: b8f4c2e91a3d
Revises: 940d9b761f7e
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8f4c2e91a3d"
down_revision: Union[str, Sequence[str], None] = "940d9b761f7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tabela_existe(nome: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nome)


def upgrade() -> None:
    if not _tabela_existe("divergencia_aceite"):
        op.create_table(
            "divergencia_aceite",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("conta_id", sa.UUID(), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("valor", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column("motivo", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["conta_id"], ["conta.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("conta_id", "data", name="uq_divergencia_conta_data"),
        )


def downgrade() -> None:
    if _tabela_existe("divergencia_aceite"):
        op.drop_table("divergencia_aceite")
