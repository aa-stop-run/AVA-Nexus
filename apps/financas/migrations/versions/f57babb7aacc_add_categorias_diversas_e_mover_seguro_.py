"""add categorias diversas e mover seguro de vida para habitacao

Revision ID: f57babb7aacc
Revises: d7836e701522
Create Date: 2026-08-01 00:27:56.905665

"""
from typing import Sequence, Union

from alembic import op

from ava.financas.categorias_iniciais import mover_categoria_de_grupo, semear_categorias


# revision identifiers, used by Alembic.
revision: str = 'f57babb7aacc'
down_revision: Union[str, Sequence[str], None] = 'd7836e701522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # "Seguro de vida" nasceu em "Impostos e seguros" (migração d6f0ed375db0) mas o utilizador
    # pediu para passar a viver em "Habitação". Não é uma categoria nova (não pode ir para
    # GRUPOS_INICIAIS/semear_categorias, que só insere pares grupo+nome inexistentes) — é a MESMA
    # categoria a mudar de grupo, para preservar o histórico de movimentos já lançados com ela.
    #
    # TEM de correr ANTES de semear_categorias: GRUPOS_INICIAIS já lista "Seguro de vida" em
    # "Habitação" (é o destino final, ver categorias_iniciais.py), por isso numa BD que ainda
    # tem a categoria antiga em "Impostos e seguros" (todas as BDs de produção não migradas),
    # semear_categorias criaria uma "Seguro de vida" NOVA em "Habitação" primeiro — e o mover
    # a seguir colidiria com essa cópia fresca ao tentar mover lá para a mesma categoria antiga.
    # Mover primeiro elimina essa janela: quando semear_categorias corre a seguir, "Habitação"
    # já tem a categoria (movida, não recriada), por isso não semeia nada a mais.
    mover_categoria_de_grupo(
        op.get_bind(),
        categoria_nome="Seguro de vida",
        grupo_origem_nome="Impostos e seguros",
        grupo_destino_nome="Habitação",
    )

    # Sementeira idempotente de novas categorias e dois grupos novos ("Animais", "Profissional")
    # — ver ava.financas.categorias_iniciais.GRUPOS_INICIAIS. Não mexe no que já existe.
    semear_categorias(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    # Nota: não reverte a sementeira nem o "mover" acima — mesma postura das migrações
    # d6f0ed375db0 e 6422b67d58c8 (dados de categoria não são o alvo de um downgrade de schema).
    pass
