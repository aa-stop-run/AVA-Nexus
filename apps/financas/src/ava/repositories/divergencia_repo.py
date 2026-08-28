"""O cálculo de onde o razão não explica o saldo — a lógica de /reconciliacao.

Nada aqui escreve uma âncora (ver tests/test_arquitetura.py): só lê `saldo_historico` através de
`saldo_historico_repo.listar_evolucao`/`obter_saldo_mais_recente`. A única escrita própria deste
módulo seria `DivergenciaAceite`, que não é uma âncora — é a dispensa, o único estado guardado.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.saldos import JANELA_CASAMENTO_DIAS, RECONCILIACAO_DESDE, sinal_de
from ava.models.conta import Conta
from ava.models.divergencia_aceite import DivergenciaAceite
from ava.models.movimento import Movimento
from ava.repositories import conta_repo, movimento_repo, saldo_historico_repo


class Divergencia(NamedTuple):
    """Uma janela entre duas âncoras consecutivas em que o razão não fecha com o banco."""

    conta: Conta
    de: date
    ate: date
    declarado: Decimal
    derivado: Decimal
    diferenca: Decimal


async def listar_divergencias(session: AsyncSession) -> list[Divergencia]:
    """Janelas entre âncoras consecutivas em que o razão não explica a variação do saldo.

    Calculada a cada pedido, nunca escrita: no instante em que `extratos.py` regista a âncora, os
    movimentos que a explicam ainda não existem — as linhas são criadas a seguir e só depois
    reconciliadas, possivelmente com revisão manual pelo meio. Detetar na importação seria
    detetar sempre (spec §10).

    Só janelas cuja âncora final seja >= RECONCILIACAO_DESDE (§11), e sem as dispensadas. Fora
    disso, três exclusões:

    - âncora final de origem `manual` — é uma reposição, não uma medição (ver abaixo).
    - âncora inicial de origem `ficheiro` — duas fotografias provisórias não delimitam um período
      mensurável (ver abaixo). Não se aplica quando a âncora inicial é `extrato`: essa janela
      continua verificada mesmo que a final seja `ficheiro`.
    - janelas dispensadas em `divergencia_aceite`.
    """
    dispensadas = {
        (d.conta_id, d.data) for d in (await session.execute(select(DivergenciaAceite))).scalars()
    }
    divergencias: list[Divergencia] = []
    for conta in await conta_repo.listar_todas_ativas(session):
        ancoras = await saldo_historico_repo.listar_evolucao(session, conta.id)
        for anterior, atual in zip(ancoras, ancoras[1:]):
            if atual.data < RECONCILIACAO_DESDE:
                continue
            # Uma âncora MANUAL não é uma medição que o razão tenha de explicar — é uma
            # declaração de reposição, o próprio mecanismo de "novo ponto de partida" que a §11
            # descreve. No dia em que o utilizador corrige à mão o saldo de uma conta (porque a
            # âncora antiga estava errada), a janela (âncora antiga → âncora manual nova) fecharia
            # sempre em divergência — e essa divergência seria exatamente a correção que ele
            # acabou de fazer. Mostrá-la violaria o princípio da própria spec, §6.3: "uma lista
            # que grita sempre não é um sinal" (revisão final, achado 3).
            if atual.origem == "manual":
                continue
            # Uma âncora de FICHEIRO como ponto de PARTIDA da janela também não delimita um
            # período mensurável: duas fotografias provisórias não bastam. O ficheiro do BPI Net
            # (spec 2026-08-09, §2.1) é um retrato do momento da exportação, não a medição de um
            # período fechado — e a cascata de datas da §3 agrava isto, porque atribui a alguns
            # lançamentos uma data ANTERIOR à do lançamento em si. Um movimento que o banco lançou
            # entre duas importações mas que a cascata data de ANTES da primeira entra no saldo
            # declarado da segunda fotografia sem que a sua data caia dentro da janela — o
            # `fluxo_entre` nunca o conta, e a aritmética não fecha por construção, não porque
            # falte nada no razão. Medido: 24% das linhas do ficheiro real recuam 1 a 4 dias, e
            # com importação diária 18 de 27 janelas apareciam assim — todas falsas, o padrão
            # anula-se na janela seguinte.
            #
            # Só uma âncora DEFINITIVA — a de extrato — pode abrir uma janela que o razão tenha de
            # explicar, porque só ela corresponde a um período que o banco fechou. Por isso o
            # filtro é sobre a âncora INICIAL, não a final: uma janela que começa num extrato e
            # acaba num ficheiro continua verificada — é a que mostra o que aconteceu desde o
            # último fecho do banco, e é a que interessa.
            if anterior.origem == "ficheiro":
                continue
            if (conta.id, atual.data) in dispensadas:
                continue
            entradas, saidas = await movimento_repo.fluxo_entre(
                session, conta.id, de=anterior.data, ate=atual.data
            )
            declarado = atual.valor - anterior.valor
            derivado = sinal_de(conta.tipo) * (entradas - saidas)
            if declarado != derivado:
                divergencias.append(
                    Divergencia(conta, anterior.data, atual.data, declarado, derivado,
                                declarado - derivado)
                )
    return divergencias


async def obter_dispensa(
    session: AsyncSession, conta_id: uuid.UUID, data: date
) -> DivergenciaAceite | None:
    """A dispensa já registada para esta janela (conta_id, data), se existir.

    Usado por `reconciliacao.dispensar` para atualizar em vez de inserir quando a mesma janela é
    dispensada duas vezes (duplo clique, ou voltar atrás e reenviar) — a unicidade é
    `(conta_id, data)`, e sem esta verificação o segundo pedido rebentava com `IntegrityError`.
    """
    result = await session.execute(
        select(DivergenciaAceite).where(
            DivergenciaAceite.conta_id == conta_id, DivergenciaAceite.data == data
        )
    )
    return result.scalar_one_or_none()


async def listar_por_confirmar_antigos(session: AsyncSession) -> list[Movimento]:
    """Movimentos por confirmar mais antigos que a última vez que o EXTRATO desta conta provou
    cobertura, com margem.

    A margem é `JANELA_CASAMENTO_DIAS`: os extratos são mensais e uma compra dos últimos dias
    antes do corte só aparece no extrato seguinte. Sem a margem, toda a compra do fim de cada mês
    apareceria aqui e a lista deixava de ser um sinal (spec §6.3).

    Não restringe a `ORIGENS_REGISTO_MANUAL`: o critério não é "o utilizador escreveu isto à mão",
    é "tudo o que o utilizador ou um documento trouxeram, e o banco ainda não corroborou" — cobre a
    família de registo manual (`manual`/`web`) e também `pipeline` (recibo) e `documento`
    (fatura), porque origem e estado de confirmação são ortogonais (§4.2): uma fatura da EDP com
    conta associada, por confirmar e mais antiga que a margem, é exatamente o que esta lista
    existe para mostrar.

    Excluídas três origens do CONJUNTO verificado:
    - `extrato` — já nasceu do banco; não é isto que se está à espera de confirmar, mesmo quando
      (por uma reconciliação ainda incompleta) ainda não tem `linha_extrato_id`.
    - `regra` — gerado pelo sistema (recorrentes, `financas/recorrentes.py`), não registado pelo
      utilizador. Já tem alerta próprio em `ingestion/reconciliacao.py` ("nunca foi
      debitado/creditado" ao fim de `JANELA_DIAS`); aparecer também aqui duplicava o mesmo sinal
      em dois sítios. E é deliberadamente excluído do casamento (`ingestion/casamento.py`, "tem
      outro dono e outro ciclo de vida"), por isso tende a ficar para sempre sem
      `linha_extrato_id` — apareceria aqui todos os meses, o mesmo falso alarme permanente que a
      margem da §6.3 já evita para o fim de mês.
    - `ficheiro` — veio de um export do banco (spec 2026-08-09, §2.3). Dizer que "o banco nunca o
      confirmou" seria um erro de categoria, e como o ficheiro cobre semanas para trás, dezenas
      apareceriam a cada importação — a mesma lista que grita sempre que a margem já evita.

    E a REFERÊNCIA do `limite`, por conta, é a âncora mais recente de origem="extrato" — não "a
    âncora mais recente, seja ela qual for". Esta lista afirma "o banco teve oportunidade de
    mostrar isto e não mostrou", e só um EXTRATO prova essa oportunidade: cobre um mês inteiro, do
    primeiro ao último dia. Uma correção manual é uma declaração de reposição, não uma medição de
    cobertura. E um ficheiro do BPI Net também não prova cobertura nenhuma — o próprio rodapé dele
    avisa que só traz o que estava no ecrã, sem prometer nenhum início (ronda de correção 1,
    Important #4).

    A versão anterior usava "a âncora mais recente, seja de que origem for" como referência, e só
    a saltava quando essa origem era `manual`/`ficheiro`. O raciocínio estava certo mas o efeito
    não tinha sido calculado: como se importa o ficheiro várias vezes por mês e o extrato chega
    uma vez, a âncora mais recente da conta principal era quase sempre `ficheiro`, e a conta
    ficava saltada ~28 dias em 30 (revisão final, achado 6). Usar diretamente a âncora mais
    recente de `origem="extrato"` resolve isto sem abrir mão da semântica: uma conta sem NENHUMA
    âncora de extrato (o caso real que motivou a pausa — os cartões de refeição, sem extrato nem
    exportação, só âncoras manuais) continua a ser saltada, porque não há cobertura provada
    nenhuma para servir de referência.
    """
    antigos: list[Movimento] = []
    for conta in await conta_repo.listar_todas_ativas(session):
        ancora_extrato = await saldo_historico_repo.obter_saldo_mais_recente_por_origem(
            session, conta.id, origem="extrato"
        )
        if ancora_extrato is None:
            continue
        limite = ancora_extrato.data - timedelta(days=JANELA_CASAMENTO_DIAS)
        resultado = await session.execute(
            select(Movimento).where(
                Movimento.conta_id == conta.id,
                Movimento.origem.not_in(("extrato", "regra", "ficheiro")),
                Movimento.linha_extrato_id.is_(None),
                Movimento.data < limite,
                Movimento.data >= RECONCILIACAO_DESDE,
            ).order_by(Movimento.data)
        )
        antigos.extend(resultado.scalars().all())
    return antigos
