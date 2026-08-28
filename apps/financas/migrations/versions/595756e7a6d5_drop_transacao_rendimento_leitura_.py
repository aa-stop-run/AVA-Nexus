"""drop transacao rendimento leitura_consumo

Revision ID: 595756e7a6d5
Revises: 520da9ca66ae
Create Date: 2026-07-30 12:20:50.286554

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '595756e7a6d5'
down_revision: Union[str, Sequence[str], None] = '520da9ca66ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Todos os produtores (faturas, Telegram, reconciliacao, recorrentes) escrevem no ledger
    (`movimento` + `movimento_linha`); `leitura_consumo`, `transacao` e `rendimento` ficaram sem
    nenhum escritor nem leitor (Tarefa 9). Ordem do drop: `leitura_consumo` primeiro (tem FK para
    `fornecedor` e `documento`), depois `transacao` (FK para `documento`, `fornecedor`, `titular`
    x2 e `conta`), depois `rendimento` (FK para `titular` e `conta`). `transacao.conta_id` tem FK
    para `conta`, que continua a existir, portanto nao ha ciclo entre as tres tabelas.
    """
    op.drop_table("leitura_consumo")
    op.drop_table("transacao")
    op.drop_table("rendimento")


def downgrade() -> None:
    """Downgrade schema.

    Recria as tres tabelas com o schema exato de antes desta tarefa, confirmado por inspecao
    direta a pg_constraint/information_schema.columns numa base de dados viva ainda no schema
    antigo (nao só pelos ficheiros de migração originais): `leitura_consumo` e `transacao` foram
    criadas em 88e5136bde47 com FKs sem nome explicito (o Postgres deu-lhes o nome automatico
    "<tabela>_<coluna>_fkey"); `transacao.conta_id` foi acrescentada depois, em 3f881d0aa904,
    também sem nome (idem); `rendimento` foi criada em cf59190c319a e perdeu a FK
    `rendimento_recorrente_id_fkey` (para a extinta `rendimento_recorrente`) em 520da9ca66ae — não
    a recriamos aqui, porque essa nao e a forma da tabela imediatamente antes desta migracao.
    Todas as FKs abaixo levam nome explicito para nao repetir o problema descrito em
    90916ca78573 (drop_constraint(None, ...) falha num downgrade futuro).
    """
    op.create_table(
        "rendimento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("titular_id", sa.UUID(), nullable=False),
        sa.Column("conta_id", sa.UUID(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("recorrente_id", sa.UUID(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conta_id"], ["conta.id"], name="rendimento_conta_id_fkey"),
        sa.ForeignKeyConstraint(["titular_id"], ["titular.id"], name="rendimento_titular_id_fkey"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "transacao",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=True),
        sa.Column("fornecedor_id", sa.UUID(), nullable=True),
        sa.Column("titular_id", sa.UUID(), nullable=True),
        sa.Column("registado_por", sa.UUID(), nullable=True),
        sa.Column("valor", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("categoria", sa.String(length=50), nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("ambito", sa.String(length=10), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("descricao", sa.String(length=255), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("conta_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["documento_id"], ["documento.id"], name="transacao_documento_id_fkey"),
        sa.ForeignKeyConstraint(["fornecedor_id"], ["fornecedor.id"], name="transacao_fornecedor_id_fkey"),
        sa.ForeignKeyConstraint(["registado_por"], ["titular.id"], name="transacao_registado_por_fkey"),
        sa.ForeignKeyConstraint(["titular_id"], ["titular.id"], name="transacao_titular_id_fkey"),
        sa.ForeignKeyConstraint(["conta_id"], ["conta.id"], name="transacao_conta_id_fkey"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "leitura_consumo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("documento_id", sa.UUID(), nullable=False),
        sa.Column("fornecedor_id", sa.UUID(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("quantidade", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("unidade", sa.String(length=10), nullable=False),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fim", sa.Date(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["documento_id"], ["documento.id"], name="leitura_consumo_documento_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["fornecedor_id"], ["fornecedor.id"], name="leitura_consumo_fornecedor_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fornecedor_id", "periodo_inicio", "periodo_fim", name="uq_leitura_periodo_fornecedor"
        ),
    )
