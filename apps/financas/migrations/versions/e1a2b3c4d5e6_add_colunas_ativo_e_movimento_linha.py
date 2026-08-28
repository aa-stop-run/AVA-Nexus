"""add colunas ativo e movimento_linha

Revision ID: e1a2b3c4d5e6
Revises: ca356e27c264
Create Date: 2026-08-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'ca356e27c264'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists in the table."""
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        f"WHERE table_name='{table_name}' AND column_name='{column_name}'"
    ))
    return result.scalar() > 0


def upgrade() -> None:
    """Add missing columns to ativo and movimento_linha tables."""
    
    # Add missing columns to ativo
    if not _column_exists('ativo', 'tipo'):
        op.add_column('ativo', sa.Column('tipo', sa.String(length=20), nullable=True))
        op.execute("UPDATE ativo SET tipo = 'veiculo'")
        op.alter_column('ativo', 'tipo', nullable=False)
    
    if not _column_exists('ativo', 'valor_atual'):
        op.add_column('ativo', sa.Column('valor_atual', sa.Numeric(precision=12, scale=2), nullable=True))
        op.execute("UPDATE ativo SET valor_atual = 0.00")
        op.alter_column('ativo', 'valor_atual', nullable=False)
    
    # Rename matricula -> data_aquisicao if still named matricula
    if _column_exists('ativo', 'matricula') and not _column_exists('ativo', 'data_aquisicao'):
        op.alter_column('ativo', 'matricula', new_column_name='data_aquisicao', existing_type=sa.Date(), nullable=True)

    # Add missing columns to movimento_linha
    if not _column_exists('movimento_linha', 'ativo_id'):
        op.add_column('movimento_linha', sa.Column('ativo_id', sa.UUID(), nullable=True))
        op.create_foreign_key('fk_movimento_linha_ativo_id', 'movimento_linha', 'ativo', ['ativo_id'], ['id'])
    
    if not _column_exists('movimento_linha', 'conta_relacionada_id'):
        op.add_column('movimento_linha', sa.Column('conta_relacionada_id', sa.UUID(), nullable=True))
        op.create_foreign_key('fk_movimento_linha_conta_relacionada_id', 'movimento_linha', 'conta', ['conta_relacionada_id'], ['id'])
    
    if not _column_exists('movimento_linha', 'leitura_odometro'):
        op.add_column('movimento_linha', sa.Column('leitura_odometro', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove the added columns."""
    op.drop_constraint('fk_movimento_linha_ativo_id', 'movimento_linha', type_='foreignkey')
    op.drop_constraint('fk_movimento_linha_conta_relacionada_id', 'movimento_linha', type_='foreignkey')
    op.drop_column('movimento_linha', 'leitura_odometro')
    op.drop_column('movimento_linha', 'conta_relacionada_id')
    op.drop_column('movimento_linha', 'ativo_id')

    op.alter_column('ativo', 'data_aquisicao', new_column_name='matricula', existing_type=sa.Date(), nullable=True)
    op.drop_column('ativo', 'valor_atual')
    op.drop_column('ativo', 'tipo')
