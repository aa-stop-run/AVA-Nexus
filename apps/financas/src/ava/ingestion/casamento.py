"""Casar uma linha de extrato com um movimento que o utilizador já tinha registado.

Sem isto, o saldo derivado contaria em dobro tudo o que fosse registado à mão e depois
aparecesse no extrato — e quanto mais disciplinado o utilizador fosse, pior ficaria (spec
2026-08-08, §9).

Só valor exato e data. Nunca descrição: casar por texto é o padrão que a spec de 2026-08-06
removeu deliberadamente, e reintroduzi-lo aqui traria de volta o mesmo problema noutra roupagem.
"""

from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.saldos import JANELA_CASAMENTO_DIAS
from ava.models.linha_extrato import LinhaExtrato
from ava.models.movimento import Movimento
from ava.repositories import linha_extrato_repo, movimento_repo


# Origens que o extrato pode confirmar: o que o utilizador registou à mão, e o que veio de um
# ficheiro do banco (spec 2026-08-09, §5). Fica de fora `regra` — gerado pelo sistema, tem alerta
# próprio e outro ciclo de vida — e `extrato`, que já nasceu confirmado.
ORIGENS_POR_CONFIRMAR = movimento_repo.ORIGENS_REGISTO_MANUAL + ("ficheiro",)


async def casar_linha(session: AsyncSession, linha: LinhaExtrato) -> bool:
    """Liga a linha a um movimento por confirmar do mesmo valor, se houver um.

    Devolve `True` quando casou (e já marcou a linha conciliada), `False` quando não havia par e
    o chamador deve seguir o caminho normal de criar um movimento novo.

    O lado a procurar sai do sinal da linha, tal como `reconciliacao._resolver_transferencia` já
    faz: uma linha negativa confirma o lado de origem (`linha_extrato_id`), uma positiva confirma
    o lado de destino de uma transferência (`linha_extrato_destino_id`) ou o lado de origem de
    uma entrada (`linha_extrato_id`).

    Emparelhamento em GRUPO, não um a um: entre vários candidatos empatados no mesmo valor e
    dentro da janela, qualquer um serve — dois cafés de 2,50€ no mesmo dia casam com duas linhas
    de 2,50€ sem ambiguidade real nenhuma, por isso nunca vai para revisão manual por causa disto.
    """
    valor = abs(linha.valor)
    inicio = linha.data - timedelta(days=JANELA_CASAMENTO_DIAS)
    fim = linha.data + timedelta(days=JANELA_CASAMENTO_DIAS)

    if linha.valor < 0:
        # Saída, ou a perna de ORIGEM de uma transferência — ambas vivem em conta_id/linha_extrato_id.
        lado = and_(
            Movimento.conta_id == linha.conta_id,
            Movimento.linha_extrato_id.is_(None),
            Movimento.tipo.in_(("saida", "transferencia")),
        )
    else:
        # Entrada (conta_id/linha_extrato_id) OU a perna de DESTINO de uma transferência
        # (conta_destino_id/linha_extrato_destino_id) — nunca as duas colunas ao mesmo tempo.
        lado = or_(
            and_(
                Movimento.conta_destino_id == linha.conta_id,
                Movimento.linha_extrato_destino_id.is_(None),
                Movimento.tipo == "transferencia",
            ),
            and_(
                Movimento.conta_id == linha.conta_id,
                Movimento.linha_extrato_id.is_(None),
                Movimento.tipo == "entrada",
            ),
        )

    resultado = await session.execute(
        select(Movimento)
        .where(
            Movimento.valor == valor,
            Movimento.data >= inicio,
            Movimento.data <= fim,
            # Só as origens "por confirmar" — ver o porquê de cada uma no comentário de
            # ORIGENS_POR_CONFIRMAR acima. Um movimento gerado por regra (recorrente) ou por
            # documento (fatura) tem outro dono e outro ciclo de vida; deixá-lo casar aqui
            # suprimiria em silêncio o alerta "nunca foi debitado/creditado" (ver
            # verificar_movimentos_sem_extrato em reconciliacao.py) para um movimento que nunca
            # teve nada a ver com esta linha.
            Movimento.origem.in_(ORIGENS_POR_CONFIRMAR),
            lado,
        )
        .order_by(Movimento.data, Movimento.id)
    )
    candidatos = list(resultado.scalars().all())
    if not candidatos:
        return False

    # Data mais próxima primeiro; empates desempatam pela data mais antiga e depois pelo id, para
    # o resultado ser determinístico (a query já vem ordenada por data/id, mas o sort explícito
    # não depende disso) e os testes poderem afirmar qual dos candidatos ficou ligado.
    candidatos.sort(key=lambda m: (abs((m.data - linha.data).days), m.data, m.id))
    movimento = candidatos[0]

    if linha.valor < 0 or movimento.tipo == "entrada":
        movimento.linha_extrato_id = linha.id
    else:
        movimento.linha_extrato_destino_id = linha.id

    # marcar_conciliada_sem_ligar, não marcar_conciliada: a ligação já foi feita acima, no campo
    # certo consoante o lado (linha_extrato_id OU linha_extrato_destino_id). marcar_conciliada
    # escreve sempre em linha_extrato_id via movimento_repo.ligar_a_linha_extrato — chamá-la aqui
    # sobrescreveria essa coluna também no caso de destino, inventando uma segunda ligação onde só
    # devia existir uma (mesmo motivo documentado em marcar_conciliada_sem_ligar).
    await linha_extrato_repo.marcar_conciliada_sem_ligar(session, linha.id)
    # flush explícito: `movimento` já estava no identity map (veio da query acima), por isso o
    # session.get() dentro de marcar_conciliada_sem_ligar não dispara autoflush nenhum — sem isto,
    # a alteração a movimento.linha_extrato_id/linha_extrato_destino_id fica só em memória e um
    # refresh() do chamador (ou outra leitura na mesma transação) não a veria.
    await session.flush()
    return True
