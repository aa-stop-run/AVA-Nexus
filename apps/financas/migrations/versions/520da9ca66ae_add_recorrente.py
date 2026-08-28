"""add recorrente

Revision ID: 520da9ca66ae
Revises: 90916ca78573
Create Date: 2026-07-30 10:25:44.509756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '520da9ca66ae'
down_revision: Union[str, Sequence[str], None] = '90916ca78573'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    `recorrente` generaliza `rendimento_recorrente` (Tarefa 7): passa a servir também saídas
    (renda, prestações, subscrições), não só entradas, o que é o que habilita a comparação
    "esperado vs. real". Nomes de FK explícitos em tudo — ver aa0f40c6833b para o porquê.

    A FK `movimento_recorrente_id_fkey` estava deliberadamente por acrescentar desde a Tarefa 3
    (`movimento.recorrente_id` nasceu sem ForeignKey porque `recorrente` ainda não existia — ver o
    comentário em ava/models/movimento.py). É acrescentada aqui, agora que a tabela existe.

    `rendimento.recorrente_id` tinha uma FK para `rendimento_recorrente`
    (`rendimento_recorrente_id_fkey`, ver cf59190c319a). Essa FK tem de ser largada antes de
    largar `rendimento_recorrente`, senão o DROP TABLE falha por dependência. `rendimento` em si
    não faz parte desta tarefa — fica com a coluna, sem FK, tal como `movimento.recorrente_id`
    ficou até aqui.
    """
    op.create_table(
        "recorrente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=15), nullable=False),
        sa.Column("categoria_id", sa.UUID(), nullable=False),
        sa.Column("conta_id", sa.UUID(), nullable=True),
        sa.Column("titular_id", sa.UUID(), nullable=False),
        sa.Column("valor", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("dia_do_mes", sa.Integer(), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["categoria_id"], ["categoria.id"], name="recorrente_categoria_id_fkey"),
        sa.ForeignKeyConstraint(["conta_id"], ["conta.id"], name="recorrente_conta_id_fkey"),
        sa.ForeignKeyConstraint(["titular_id"], ["titular.id"], name="recorrente_titular_id_fkey"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_foreign_key(
        "movimento_recorrente_id_fkey", "movimento", "recorrente", ["recorrente_id"], ["id"]
    )

    op.drop_constraint("rendimento_recorrente_id_fkey", "rendimento", type_="foreignkey")
    op.drop_table("rendimento_recorrente")


def downgrade() -> None:
    """Downgrade schema.

    Recria `rendimento_recorrente` com o schema exato de cf59190c319a (incluindo `criado_em`,
    que `recorrente` nunca teve) e a FK de volta em `rendimento.recorrente_id`, larga a FK nova
    em `movimento` e a tabela `recorrente`.
    """
    op.create_table(
        "rendimento_recorrente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("titular_id", sa.UUID(), nullable=False),
        sa.Column("conta_id", sa.UUID(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("dia_do_mes", sa.Integer(), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conta_id"], ["conta.id"], name="rendimento_recorrente_conta_id_fkey"),
        sa.ForeignKeyConstraint(["titular_id"], ["titular.id"], name="rendimento_recorrente_titular_id_fkey"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "rendimento_recorrente_id_fkey",
        "rendimento",
        "rendimento_recorrente",
        ["recorrente_id"],
        ["id"],
    )

    op.drop_constraint("movimento_recorrente_id_fkey", "movimento", type_="foreignkey")
    op.drop_table("recorrente")
