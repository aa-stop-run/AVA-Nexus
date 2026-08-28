import logging
from datetime import UTC, date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.recorrentes import gerar_movimentos_recorrentes_do_mes
from ava.ingestion.pipeline import processar_documentos_pendentes, processar_extratos_pendentes, processar_recibos_pendentes
from ava.ingestion.reconciliacao import verificar_movimentos_sem_extrato
from ava.obrigacoes.regras import sincronizar_obrigacoes_ativo
from ava.repositories import alerta_repo, fila_repo, ativo_repo

logger = logging.getLogger("ava.alerts")

IDADE_MAXIMA_FILA_DIAS = 3


async def verificar_idade_da_fila(session: AsyncSession) -> list[str]:
    pendentes = await fila_repo.listar_pendentes_ou_em_processamento(session)
    limite = datetime.now(UTC) - timedelta(days=IDADE_MAXIMA_FILA_DIAS)

    novas_chaves = []
    for item in pendentes:
        if item.criado_em < limite:
            chave = f"idade_fila:{item.id}"
            alerta = await alerta_repo.criar_se_novo(
                session,
                tipo="idade_fila",
                chave_deduplicacao=chave,
                mensagem=(
                    f"Documento pendente há mais de {IDADE_MAXIMA_FILA_DIAS} dias na fila de "
                    f"estruturação (item {item.id})."
                ),
            )
            if alerta is not None:
                novas_chaves.append(chave)
    await session.commit()
    return novas_chaves


async def verificar_falhas_de_ingestao(session: AsyncSession) -> list[str]:
    itens_com_erro = await fila_repo.listar_com_erro(session)

    novas_chaves = []
    for item in itens_com_erro:
        chave = f"falha_ingestao:{item.id}"
        mensagem_erro = (item.resultado_json or {}).get("erro", "erro desconhecido")
        alerta = await alerta_repo.criar_se_novo(
            session,
            tipo="falha_ingestao",
            chave_deduplicacao=chave,
            mensagem=f"Falha ao estruturar o documento (item {item.id}): {mensagem_erro}",
        )
        if alerta is not None:
            novas_chaves.append(chave)
    await session.commit()
    return novas_chaves


async def sincronizar_obrigacoes_dos_ativos_ativos(session: AsyncSession, *, referencia: date) -> None:
    ativos = await ativo_repo.listar_todos_ativos(session)
    # Extraídos para tuplos simples ANTES do loop começar: se um ativo falhar a meio, o
    # except abaixo faz session.rollback(), que expira TODOS os objetos ORM da sessão — não só
    # o que falhou. Sem isto, a iteração seguinte do loop rebentaria com MissingGreenlet ao
    # tentar ler um atributo expirado (ativo.titular_id) fora de um await explícito. Desacoplar
    # o loop do estado ORM à partida evita depender da ordem de leitura vs. rollback. `nome` foi
    # acrescentado (fix batch E) pela mesma razão: sincronizar_obrigacoes_ativo precisa dele
    # para desambiguar obrigações de ativos diferentes na descricao.
    # Só veículos COM data de aquisição: `Ativo` deixou de ser exclusivamente `veiculo` (passou a
    # cobrir casas e outros bens, ver ativo_repo.TIPOS_VEICULO) e `data_aquisicao` é nullable —
    # gerar uma "Inspeção periódica obrigatória" para uma casa é errado, e calcular_proxima_inspecao
    # rebentaria com None. Ambos os filtros vivem AQUI e não dentro do try do loop: um ativo
    # inelegível não é uma falha a assinalar, é simplesmente um ativo que este job não trata.
    dados_ativos = [
        (v.id, v.titular_id, v.data_aquisicao, v.nome)
        for v in ativos
        if v.tipo in ativo_repo.TIPOS_VEICULO and v.data_aquisicao is not None
    ]

    for ativo_id, titular_id, matricula, nome in dados_ativos:
        try:
            await sincronizar_obrigacoes_ativo(
                session,
                titular_id=titular_id,
                matricula=matricula,
                referencia=referencia,
                ativo_id=ativo_id,
                ativo_nome=nome,
            )
        except Exception:  # noqa: BLE001 — um ativo avariado não pode bloquear os restantes (A-P6)
            # listar_todos_ativos não tem ORDER BY, por isso um ativo persistentemente
            # avariado ficaria sempre algures na lista e, sem isolamento por-ativo, impediria
            # as obrigações de qualquer outro ativo do agregado de serem geradas — o oposto do
            # que este job existe para garantir.
            logger.exception(
                "Falha ao sincronizar obrigações do ativo %s (titular %s)",
                ativo_id,
                titular_id,
            )
            # A sessão pode ter ficado num estado de flush falhado a meio de
            # sincronizar_obrigacoes_ativo — reverte-se antes de a reutilizar para sinalizar e
            # seguir para o próximo ativo.
            await session.rollback()
            # Mesmo mecanismo de alerta ativo de _alertar_revisao_manual / linhas_extrato_ignoradas
            # (ava.ingestion.pipeline): um job que continua a falhar-e-ignorar silenciosamente as obrigações
            # de um ativo, corrida após corrida, é a mesma classe de "o utilizador tem de saber"
            # que já motivou esses alertas — um log que ninguém consulta não chega (A-P6). A
            # referência entra na chave de deduplicação para não silenciar o alerta para sempre
            # após o primeiro dia caso a falha persista (ao contrário de idade_fila/falha_ingestao,
            # aqui não há um estado da fila que resolva a duplicação por si só).
            await alerta_repo.criar_se_novo(
                session,
                tipo="falha_obrigacoes_ativo",
                chave_deduplicacao=(
                    f"falha_obrigacoes_ativo:{ativo_id}:{referencia.isoformat()}"
                ),
                mensagem=(
                    f"Falha ao sincronizar obrigações do ativo {ativo_id} "
                    f"(titular {titular_id}) para a referência {referencia.isoformat()}. "
                    "Consulte os logs do scheduler para detalhes."
                ),
            )
            await session.commit()


def iniciar_scheduler(session_factory, paperless_client) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def job_ingestao() -> None:
        async with session_factory() as session:
            await processar_documentos_pendentes(session, paperless_client, referencia=date.today())
            await processar_extratos_pendentes(session, paperless_client, referencia=date.today())
            await processar_recibos_pendentes(session, paperless_client, referencia=date.today())

    async def job_alertas() -> None:
        async with session_factory() as session:
            await verificar_idade_da_fila(session)
            await verificar_falhas_de_ingestao(session)
            # Os alertas ficam registados e são consultados em /alertas (e no badge da barra lateral).
            await verificar_movimentos_sem_extrato(session, referencia=date.today())

    async def job_rendimentos() -> None:
        async with session_factory() as session:
            await gerar_movimentos_recorrentes_do_mes(session, referencia=date.today())

    async def job_obrigacoes() -> None:
        async with session_factory() as session:
            await sincronizar_obrigacoes_dos_ativos_ativos(session, referencia=date.today())

    scheduler.add_job(job_ingestao, "interval", minutes=10, id="ingestao")
    scheduler.add_job(job_alertas, "interval", minutes=15, id="alertas")
    scheduler.add_job(job_rendimentos, "interval", hours=12, id="rendimentos")
    scheduler.add_job(job_obrigacoes, "interval", hours=12, id="obrigacoes")
    scheduler.start()
    return scheduler
