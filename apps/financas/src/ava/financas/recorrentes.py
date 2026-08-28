import calendar
import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from ava.repositories import alerta_repo, movimento_repo, recorrente_repo

logger = logging.getLogger("ava.financas")


def data_do_mes(referencia: date, dia_do_mes: int) -> date:
    """Encaixa o dia configurado no mês da referência, sem estourar em meses curtos.
    Um recorrente a dia 31 cai a 30 em abril e a 28/29 em fevereiro."""
    ultimo = calendar.monthrange(referencia.year, referencia.month)[1]
    return date(referencia.year, referencia.month, min(dia_do_mes, ultimo))


async def gerar_movimentos_recorrentes_do_mes(session: AsyncSession, *, referencia: date) -> int:
    """Cria os movimentos do mês da referência para cada recorrente ativo. Idempotente.

    A idempotência é por (recorrente, ano-mês) — ver movimento_repo.existe_do_recorrente_no_mes —
    não por data exata: se o dia_do_mes mudar a meio do mês, não se gera um segundo movimento
    para o mesmo mês.

    Só gera o movimento quando o dia configurado já chegou no mês da referência
    (referencia.day >= dia encaixado, via data_do_mes — não o dia_do_mes cru, senão um
    recorrente a dia 31 nunca geraria em meses de 30 dias). Sem esta porta, um recorrente a
    dia 28 seria lançado já no dia 1 do mês, com data futura, distorcendo o "sobrou ou faltou
    dinheiro este mês" e disparando falsos alertas de reconciliação contra movimentos que
    ainda não têm correspondência no extrato.
    """
    criados = 0

    # Extraídos para tuplos simples ANTES do loop começar — mesmo motivo de
    # sincronizar_obrigacoes_dos_ativos_ativos (ava.alerts.scheduler): se um recorrente falhar
    # a meio (ver except abaixo, Achado Importante da revisão final Fase A), o rollback expira
    # TODOS os objetos ORM da sessão, não só o que falhou — ler um atributo de um recorrente
    # ainda por processar depois desse rollback rebentaria com MissingGreenlet.
    recorrentes = [
        (r.id, r.tipo, r.categoria_id, r.conta_id, r.titular_id, r.valor, r.dia_do_mes, r.descricao)
        for r in await recorrente_repo.listar_ativos(session)
    ]

    for recorrente_id, tipo, categoria_id, conta_id, titular_id, valor, dia_do_mes, descricao in recorrentes:
        data = data_do_mes(referencia, dia_do_mes)
        if referencia.day < data.day:
            continue  # ainda não chegou o dia deste mês (comparação contra o dia já encaixado)

        if await movimento_repo.existe_do_recorrente_no_mes(
            session, recorrente_id=recorrente_id, ano=referencia.year, mes=referencia.month
        ):
            continue

        try:
            await movimento_repo.criar_movimento(
                session,
                tipo=tipo,
                valor=valor,
                data=data,
                origem="regra",
                descricao=descricao,
                conta_id=conta_id,
                titular_id=titular_id,
                recorrente_id=recorrente_id,
                linhas=[movimento_repo.LinhaNova(valor=valor, categoria_id=categoria_id)],
            )
        except Exception:  # noqa: BLE001 — um recorrente mal configurado não pode bloquear os restantes (A-P6)
            # Achado Importante (revisão final Fase A): sem isolamento por-item, um único
            # recorrente com valor <= 0 (ex. introduzido via /rendimentos-recorrentes/novo antes
            # da validação de movimento_repo.ValorNaoPositivo existir, ou por engano futuro) faria
            # criar_movimento levantar e interromperia o ciclo, impedindo TODOS os recorrentes
            # seguintes deste mês de gerarem o seu movimento — o oposto do que este job existe
            # para garantir. Mesmo padrão de sincronizar_obrigacoes_dos_ativos_ativos: log +
            # rollback (a sessão pode ter ficado num estado de flush falhado) + alerta ativo +
            # continuação para o próximo recorrente.
            logger.exception(
                "Falha ao gerar o movimento recorrente do mês para o recorrente %s (titular %s)",
                recorrente_id,
                titular_id,
            )
            await session.rollback()
            await alerta_repo.criar_se_novo(
                session,
                tipo="falha_recorrente",
                chave_deduplicacao=(
                    f"falha_recorrente:{recorrente_id}:{referencia.year}-{referencia.month:02d}"
                ),
                mensagem=(
                    f"Falha ao gerar o movimento recorrente do mês {referencia.year}-"
                    f"{referencia.month:02d} para o recorrente {recorrente_id} "
                    f"(titular {titular_id}). Consulte os logs do scheduler para detalhes."
                ),
            )
            await session.commit()
            continue

        criados += 1
        # Achado 3 (revisão final de fecho da Fase A): o rollback do except acima desfazia não só
        # o recorrente que falhou, mas TAMBÉM os movimentos já criados (flush()ados mas nunca
        # commitados) pelos recorrentes anteriores do mesmo ciclo — porque o único commit vivia no
        # fim da função inteira. Um recorrente saudável processado antes de um inválido via
        # criar_movimento com sucesso, e depois via o seu movimento apagado pelo rollback do
        # recorrente seguinte: o mesmo dano que o isolamento por-item devia eliminar. Commitar aqui,
        # logo após cada sucesso, é o mesmo padrão de
        # sincronizar_obrigacoes_dos_ativos_ativos/sincronizar_obrigacoes_ativo (cada item
        # bem-sucedido é commitado individualmente, não só no fim do ciclo).
        await session.commit()

    await session.commit()
    return criados
