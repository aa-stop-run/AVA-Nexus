"""categoria.natureza: o que e fiavel e o que e compromisso

Revision ID: c4a7e2f81b6d
Revises: d1e5a93c72f4
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from ava.financas.categorias_iniciais import marcar_naturezas, semear_categorias

revision: str = "c4a7e2f81b6d"
down_revision: Union[str, Sequence[str], None] = "d1e5a93c72f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Três passos, e a ordem é a especificação: a coluna entra NULLABLE (não há valor único que
    # sirva para receitas e despesas ao mesmo tempo), marcar_naturezas preenche-a toda, e só
    # depois se aperta para NOT NULL + CHECK. Entrar já com server_default obrigaria a escolher
    # um default que viola a constraint para metade das linhas.
    op.add_column("categoria", sa.Column("natureza", sa.String(length=15), nullable=True))

    # semear_categorias primeiro: numa BD que ainda não tenha alguma categoria do seed, ela é
    # criada agora — e já com a natureza certa, porque GRUPOS_INICIAIS a transporta. Sem isto,
    # uma categoria criada aqui ficaria a NULL e o SET NOT NULL a seguir rebentava.
    semear_categorias(op.get_bind())
    marcar_naturezas(op.get_bind())

    op.alter_column("categoria", "natureza", nullable=False)
    op.create_check_constraint(
        "ck_categoria_natureza",
        "categoria",
        "(tipo = 'receita' AND natureza IN ('recorrente', 'extraordinario'))"
        " OR (tipo = 'despesa' AND natureza IN ('fixa', 'variavel', 'poupanca'))",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_categoria_natureza", "categoria", type_="check")
    op.drop_column("categoria", "natureza")
