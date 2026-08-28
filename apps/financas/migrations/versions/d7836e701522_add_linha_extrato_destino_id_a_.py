"""add linha_extrato_destino_id a movimento

Revision ID: d7836e701522
Revises: 6422b67d58c8
Create Date: 2026-07-31 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7836e701522'
down_revision: Union[str, Sequence[str], None] = '6422b67d58c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Um movimento tipo="transferencia" entre uma conta à ordem e uma conta de dívida (ex.:
    # amortização de crédito) é evidenciado por DUAS linhas de extrato distintas — uma em cada
    # conta, cada uma no seu próprio extrato bancário. linha_extrato_id (já existente) liga o
    # lado de origem; linha_extrato_destino_id liga o lado de destino, espelhando o par
    # conta_id/conta_destino_id já existente.
    op.add_column('movimento', sa.Column('linha_extrato_destino_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'movimento_linha_extrato_destino_id_fkey',
        'movimento',
        'linha_extrato',
        ['linha_extrato_destino_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('movimento_linha_extrato_destino_id_fkey', 'movimento', type_='foreignkey')
    op.drop_column('movimento', 'linha_extrato_destino_id')
