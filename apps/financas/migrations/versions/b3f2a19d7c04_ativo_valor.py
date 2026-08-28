"""ativo_valor: historico de avaliacoes e taxa por ativo

Substitui a coluna unica e mutavel `ativo.valor_atual` por uma serie datada. Ver a spec
docs/superpowers/specs/2026-08-05-valorizacao-de-ativos-design.md.

Revision ID: b3f2a19d7c04
Revises: c8d1f04b7e29
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from ava.financas.backfill_ativo_valor import backfill_ativo_valor

revision: str = "b3f2a19d7c04"
down_revision: Union[str, Sequence[str], None] = "c8d1f04b7e29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tabela_existe(nome: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nome)


def _coluna_existe(tabela: str, coluna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == coluna for c in inspector.get_columns(tabela))


def upgrade() -> None:
    if not _tabela_existe("ativo_valor"):
        op.create_table(
            "ativo_valor",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("ativo_id", sa.UUID(), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("valor", sa.Numeric(precision=12, scale=2), nullable=False),
            sa.Column("origem", sa.String(length=12), nullable=False, server_default="observado"),
            sa.Column(
                "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["ativo_id"], ["ativo.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ativo_id", "data", name="uq_ativo_valor_ativo_data"),
        )
        op.create_index("ix_ativo_valor_ativo_id", "ativo_valor", ["ativo_id"])

    if not _coluna_existe("ativo", "taxa_anual"):
        op.add_column("ativo", sa.Column("taxa_anual", sa.Numeric(precision=5, scale=4), nullable=True))

    # Só depois da tabela existir: converte valor_atual na primeira observação, datada de HOJE.
    # A coluna NÃO é removida aqui — expand/contract. Cai na Task 9, depois de todo o código
    # que a lê ter desaparecido. Sem isso, entre esta migração e a Task 5 a app rebentava a
    # selecionar uma coluna inexistente.
    if _coluna_existe("ativo", "valor_atual"):
        criadas = backfill_ativo_valor(op.get_bind())
        print(f"backfill_ativo_valor: {criadas} avaliacoes criadas")


def downgrade() -> None:
    op.drop_column("ativo", "taxa_anual")
    op.drop_index("ix_ativo_valor_ativo_id", table_name="ativo_valor")
    op.drop_table("ativo_valor")
