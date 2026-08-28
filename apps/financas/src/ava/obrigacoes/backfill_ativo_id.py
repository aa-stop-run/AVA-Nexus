import uuid

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from ava.models.obrigacao import Obrigacao
from ava.models.ativo import Ativo

# Tipos de obrigação gerados por sincronizar_obrigacoes_ativo (ver ava.obrigacoes.regras) —
# os únicos que sempre tiveram um ativo por trás, mesmo antes de a coluna existir.
TIPOS_ASSOCIADOS_A_ATIVO = ("inspecao", "iuc")


def backfill_ativo_id_obrigacoes_regra(connection: Connection) -> int:
    """Preenche `ativo_id` em obrigações pré-existentes deixadas a NULL pela migração
    `b2a9258c1b44` (que acrescentou a coluna).

    Contexto: `obrigacao_repo.existe_obrigacao` passou a incluir `ativo_id` na chave de
    dedupe (tipo, data_limite, titular_id, ativo_id). Qualquer `Obrigacao` criada antes
    dessa migração tem `ativo_id IS NULL`, e em SQL `NULL = 'algum-uuid'` nunca é
    verdadeiro — por isso, sem este backfill, a próxima corrida de `job_obrigacoes`
    recalcularia a mesma data_limite para o mesmo veículo e não reconheceria a linha
    antiga como já existente, criando um duplicado silencioso para cada veículo que já
    tinha uma obrigação registada antes da migração.

    Só atualiza o caso NÃO ambíguo: titular com exatamente um `Ativo` associado
    (qualquer estado — ativo ou não; uma obrigação antiga pode pertencer a um veículo
    entretanto marcado inativo/vendido, e deve continuar corretamente atribuída a ele).
    Titulares com zero ou vários veículos ficam intencionalmente com `ativo_id` por
    preencher — o veículo correto é indeterminável a partir dos dados existentes, e este
    codebase não adivinha entre candidatos ambíguos (mesmo princípio já aplicado em
    `existe_obrigacao`).

    Recebe uma `Connection` síncrona (ex.: `op.get_bind()` dentro de uma migração
    Alembic, ou `await async_connection.run_sync(...)` num teste) — não uma `AsyncSession`
    — porque é isso que o contexto de migração do Alembic disponibiliza (ver
    `migrations/env.py`: `connection.run_sync(do_run_migrations)`).

    Devolve o número de obrigações atualizadas.
    """
    obrigacoes_pendentes = connection.execute(
        select(Obrigacao.id, Obrigacao.titular_id).where(
            Obrigacao.origem == "regra",
            Obrigacao.tipo.in_(TIPOS_ASSOCIADOS_A_ATIVO),
            Obrigacao.ativo_id.is_(None),
            Obrigacao.titular_id.is_not(None),
        )
    ).all()

    if not obrigacoes_pendentes:
        return 0

    titular_ids = {titular_id for _, titular_id in obrigacoes_pendentes}
    ativo_unico_por_titular: dict[uuid.UUID, uuid.UUID] = {}
    for titular_id in titular_ids:
        ativo_ids = connection.execute(
            select(Ativo.id).where(Ativo.titular_id == titular_id)
        ).all()
        if len(ativo_ids) == 1:
            ativo_unico_por_titular[titular_id] = ativo_ids[0][0]

    atualizadas = 0
    for obrigacao_id, titular_id in obrigacoes_pendentes:
        ativo_id = ativo_unico_por_titular.get(titular_id)
        if ativo_id is None:
            continue
        connection.execute(
            update(Obrigacao).where(Obrigacao.id == obrigacao_id).values(ativo_id=ativo_id)
        )
        atualizadas += 1

    return atualizadas
