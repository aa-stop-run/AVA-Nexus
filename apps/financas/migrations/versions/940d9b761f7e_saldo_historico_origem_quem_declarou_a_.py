"""saldo_historico.origem: quem declarou a ancora

Ver docs/superpowers/specs/2026-08-08-saldo-derivado-design.md §7: uma âncora é o que uma fonte
externa declarou — nunca calculada a partir dos movimentos. Esta coluna diz qual das duas
únicas fontes a declarou: "extrato" (o banco) ou "manual" (o utilizador).

Revision ID: 940d9b761f7e
Revises: c91a4f7be208
Create Date: 2026-08-08 23:54:08.289545

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "940d9b761f7e"
down_revision: Union[str, Sequence[str], None] = "c91a4f7be208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coluna_existe(tabela: str, coluna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == coluna for c in inspector.get_columns(tabela))


def upgrade() -> None:
    if not _coluna_existe("saldo_historico", "origem"):
        # server_default garante que as ancoras existentes ficam com "extrato" sem precisar de
        # um UPDATE separado: vieram todas de extratos.py, a unica fonte que existia.
        op.add_column(
            "saldo_historico",
            sa.Column("origem", sa.String(length=10), nullable=False, server_default="extrato"),
        )


def downgrade() -> None:
    if _coluna_existe("saldo_historico", "origem"):
        op.drop_column("saldo_historico", "origem")
