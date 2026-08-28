"""documento.resumo_ingestao: o que a ingestao deste documento produziu

Revision ID: d1e5a93c72f4
Revises: b8f4c2e91a3d
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d1e5a93c72f4"
down_revision: Union[str, Sequence[str], None] = "b8f4c2e91a3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nulável e sem backfill: os documentos já ingeridos não têm estes números e inventá-los
    # seria pior do que não os ter. A ausência lê-se como "ingerido antes de isto existir".
    op.add_column("documento", sa.Column("resumo_ingestao", JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documento", "resumo_ingestao")
