"""linha_extrato_sem_fks_de_transacao

Revision ID: 90916ca78573
Revises: aa0f40c6833b
Create Date: 2026-07-30 04:30:50.114194

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90916ca78573'
down_revision: Union[str, Sequence[str], None] = 'aa0f40c6833b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    linha_extrato deixa de ter transacao_id e rendimento_id: a ligação a um movimento passa a
    viver num só lado, em movimento.linha_extrato_id (Tarefa 3/6), o que torna estruturalmente
    impossível o estado antigo em que ambas as colunas podiam estar preenchidas ao mesmo tempo.

    Os nomes das constraints abaixo começam por "movimento_extrato_", não "linha_extrato_": a
    Tarefa 1 renomeou a tabela com `op.rename_table("movimento_extrato", "linha_extrato")`, e no
    Postgres isso renomeia só a tabela — constraints e índices dependentes mantêm o nome antigo.
    Confirmado com uma query direta a pg_constraint antes de escrever esta migração (ver relatório
    da Tarefa 6 para o comando e a saída exatos).
    """
    op.drop_constraint("movimento_extrato_transacao_id_fkey", "linha_extrato", type_="foreignkey")
    op.drop_constraint("movimento_extrato_rendimento_id_fkey", "linha_extrato", type_="foreignkey")
    op.drop_column("linha_extrato", "transacao_id")
    op.drop_column("linha_extrato", "rendimento_id")


def downgrade() -> None:
    """Downgrade schema.

    Recria as colunas e as FKs com nome explícito — uma FK anónima faz `op.drop_constraint(None, ...)`
    falhar com CompileError ("Constraint must have a name") num downgrade futuro, como já aconteceu
    duas vezes na história deste repositório.
    """
    op.add_column("linha_extrato", sa.Column("transacao_id", sa.UUID(), nullable=True))
    op.add_column("linha_extrato", sa.Column("rendimento_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "movimento_extrato_transacao_id_fkey",
        "linha_extrato",
        "transacao",
        ["transacao_id"],
        ["id"],
    )
    op.create_foreign_key(
        "movimento_extrato_rendimento_id_fkey",
        "linha_extrato",
        "rendimento",
        ["rendimento_id"],
        ["id"],
    )
