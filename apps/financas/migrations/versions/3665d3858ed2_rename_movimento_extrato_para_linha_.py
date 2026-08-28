"""rename movimento_extrato para linha_extrato

Revision ID: 3665d3858ed2
Revises: 5538dba4e069
Create Date: 2026-07-30 00:00:00.000000

"""

from alembic import op

revision = "3665d3858ed2"
down_revision = "5538dba4e069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("movimento_extrato", "linha_extrato")


def downgrade() -> None:
    op.rename_table("linha_extrato", "movimento_extrato")
