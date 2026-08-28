"""Converte a coluna `ativo.valor_atual` numa primeira observação em `ativo_valor`.

Recebe uma Connection SÍNCRONA (op.get_bind() dentro da migração, ou run_sync num teste) — só
nisso segue o mesmo padrão de ava.obrigacoes.backfill_ativo_id: esse módulo importa os modelos
ORM (Obrigacao, Ativo), enquanto aqui se usam Table/Column locais, porque uma migração é um
artefacto congelado e não pode depender de definições que evoluem depois dela.
"""

import uuid
from datetime import date

from sqlalchemy import Column, Date, MetaData, Numeric, String, Table, insert, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Connection

_META = MetaData()

_ATIVO = Table(
    "ativo",
    _META,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("valor_atual", Numeric(12, 2)),
)

_ATIVO_VALOR = Table(
    "ativo_valor",
    _META,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("ativo_id", UUID(as_uuid=True)),
    Column("data", Date),
    Column("valor", Numeric(12, 2)),
    Column("origem", String(12)),
)


def backfill_ativo_valor(connection: Connection) -> int:
    """Cria uma observação por ativo com valor_atual > 0. Devolve quantas criou.

    A data é a de HOJE, não a data_aquisicao. `valor_atual` é o que o utilizador acredita que o
    bem vale agora — datá-lo da aquisição faria a projeção depreciá-lo outra vez desde essa data,
    e o valor colapsaria no instante da migração.

    Idempotente: salta os ativos que já tenham qualquer avaliação registada.
    """
    hoje = date.today()
    ja_avaliados = set(connection.execute(select(_ATIVO_VALOR.c.ativo_id)).scalars())

    criadas = 0
    for ativo_id, valor_atual in connection.execute(
        select(_ATIVO.c.id, _ATIVO.c.valor_atual)
    ).all():
        if ativo_id in ja_avaliados:
            continue
        if valor_atual is None or valor_atual <= 0:
            continue
        connection.execute(
            insert(_ATIVO_VALOR).values(
                id=uuid.uuid4(),
                ativo_id=ativo_id,
                data=hoje,
                valor=valor_atual,
                origem="observado",
            )
        )
        criadas += 1
    return criadas
