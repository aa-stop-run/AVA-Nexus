"""drop ativo.valor_atual

Contract do expand/contract iniciado em b3f2a19d7c04: essa migração criou `ativo_valor` e
converteu `valor_atual` na primeira observação, mas deixou a coluna de pé para o código antigo
continuar a funcionar durante o deploy. Nada a lê agora.

Revision ID: d40c7b81e5a3
Revises: b3f2a19d7c04
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d40c7b81e5a3"
down_revision: Union[str, Sequence[str], None] = "b3f2a19d7c04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coluna_existe(tabela: str, coluna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == coluna for c in inspector.get_columns(tabela))


def upgrade() -> None:
    if _coluna_existe("ativo", "valor_atual"):
        op.drop_column("ativo", "valor_atual")


def downgrade() -> None:
    if _coluna_existe("ativo", "valor_atual"):
        return
    op.add_column(
        "ativo",
        sa.Column(
            "valor_atual", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0.00"
        ),
    )
    # Repõe a observação mais recente de cada ativo, para os dados voltarem a fazer sentido.
    op.execute(
        """
        UPDATE ativo a
        SET valor_atual = v.valor
        FROM (
            SELECT DISTINCT ON (ativo_id) ativo_id, valor
            FROM ativo_valor
            ORDER BY ativo_id, data DESC
        ) v
        WHERE v.ativo_id = a.id
        """
    )
