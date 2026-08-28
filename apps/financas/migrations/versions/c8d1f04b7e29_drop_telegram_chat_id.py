"""drop titular.telegram_chat_id

O bot do Telegram foi removido: o registo rápido de despesas e rendimentos passou a ser feito na
própria aplicação (/registo e /registo-rapido) e a captura de documentos passa a ser feita
diretamente no paperless-ngx. Sem bot, um chat id não tem para onde apontar.

Os movimentos com `origem = 'telegram'` NÃO são tocados: são registo histórico do que realmente
aconteceu, e reescrevê-los falsificaria o histórico. O código que os lê (a listagem de
movimentos por categorizar e o teto de magnitude do registo rápido) aceita "manual" e "telegram"
precisamente para os continuar a servir.

Revision ID: c8d1f04b7e29
Revises: a7c4e91f20b3
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d1f04b7e29"
down_revision: Union[str, Sequence[str], None] = "a7c4e91f20b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coluna_existe(tabela: str, coluna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == coluna for c in inspector.get_columns(tabela))


def upgrade() -> None:
    if _coluna_existe("titular", "telegram_chat_id"):
        op.drop_column("titular", "telegram_chat_id")


def downgrade() -> None:
    # Repõe a coluna (vazia — os chat ids não são recuperáveis) com a unique constraint que
    # f3e22692baf6 lhe tinha dado, para o esquema voltar a ser exatamente o anterior.
    if not _coluna_existe("titular", "telegram_chat_id"):
        op.add_column("titular", sa.Column("telegram_chat_id", sa.String(length=32), nullable=True))
        op.create_unique_constraint(
            "titular_telegram_chat_id_key", "titular", ["telegram_chat_id"]
        )
