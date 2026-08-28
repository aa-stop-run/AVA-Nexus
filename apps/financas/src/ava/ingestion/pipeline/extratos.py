"""Fluxo de ingestão de extratos bancários (documentos paperless)."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ava.extraction import validadores
from ava.extraction.parsers.banco_generico import parse_banco_generico
from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido
from ava.ingestion.pipeline._comum import (
    FalhaValidacao,
    _alertar_revisao_manual,
    _iterar_documentos_pendentes,
    _obter_item_concluido_com_documento,
)
from ava.ingestion.reconciliacao import reconciliar_linhas_pendentes
from ava.integrations.paperless import PaperlessClient
from ava.models.documento import Documento
from ava.repositories import (
    alerta_repo,
    conta_repo,
    documento_repo,
    fila_repo,
    linha_extrato_repo,
    saldo_historico_repo,
)
from ava.repositories.saldo_historico_repo import SaldoDuplicado

TAG_EXTRATO_POR_ESTRUTURAR = "extrato-por-estruturar"


def validar_extrato(
    extrato: ExtratoBancario, *, referencia: date
) -> tuple[list[MovimentoExtraido], int]:
    # O saldo é uma secção obrigatória e única do extrato: uma data implausível aqui significa
    # "não confies neste documento", por isso continua a falhar o extrato inteiro (FalhaValidacao).
    if not validadores.data_plausivel(
        extrato.saldo_final.data, referencia, margem_futura_dias=1, margem_passado_dias=60
    ):
        raise FalhaValidacao(f"data de saldo implausível: {extrato.saldo_final.data}")

    # A-P3: sem saldo_inicial o checksum abaixo é impossível de calcular. O caminho nível-1 (LLM)
    # pode devolver None aqui (ver schema_extrato.py) — um extrato não verificável não é de
    # confiar, mesmo que o resto pareça bem formado, por isso falha em vez de saltar em silêncio.
    if extrato.saldo_inicial is None:
        raise FalhaValidacao(
            "extrato sem saldo inicial — o checksum é impossível e um extrato não "
            "verificável não é de confiar (A-P3)"
        )

    # Checksum de §7: saldo_final − saldo_inicial tem de igualar a soma dos movimentos TAL COMO
    # LIDOS — antes do filtro de data implausível abaixo. Ordem importa: filtrar primeiro faria o
    # checksum falhar sempre que uma data fosse descartada, transformando uma degradação tolerada
    # (Fix 7, ver loop abaixo) num erro. Comparação exata em Decimal — são cêntimos, sem
    # tolerância a definir.
    esperado = extrato.saldo_final.valor - extrato.saldo_inicial
    somado = sum((movimento.valor for movimento in extrato.movimentos), Decimal("0"))
    if esperado != somado:
        raise FalhaValidacao(
            f"checksum do extrato não fecha: saldo_final − saldo_inicial = {esperado}, "
            f"mas os movimentos lidos somam {somado} — o parse perdeu ou duplicou linhas"
        )

    # Um movimento individual com data implausível NÃO deve derrubar o extrato inteiro — mesma
    # convenção que banco_generico._construir_movimento já aplica um nível abaixo (uma linha
    # garbled degrada sozinha via linhas_nao_reconhecidas, só o saldo é "tudo ou nada"). O
    # movimento implausível é descartado individualmente e contabilizado; o resto do extrato
    # (saldo + outros movimentos) continua a ser processado normalmente.
    movimentos_validos: list[MovimentoExtraido] = []
    movimentos_descartados = 0
    for movimento in extrato.movimentos:
        if validadores.data_plausivel(
            movimento.data, referencia, margem_futura_dias=1, margem_passado_dias=90
        ):
            movimentos_validos.append(movimento)
        else:
            movimentos_descartados += 1

    return movimentos_validos, movimentos_descartados


async def _persistir_extrato(
    session: AsyncSession,
    *,
    documento: Documento,
    extrato: ExtratoBancario,
    movimentos: list[MovimentoExtraido],
    titular_id: uuid.UUID,
    linhas_ignoradas_extra: int = 0,
    resolver_por_nome: bool = False,
) -> None:
        # combinar por (titular_id, instituicao, tipo, nome) — obter_ou_criar_por_instituicao (sem
    # "nome") fundiria "Crédito Pessoal" e "Mortgage & Loans/Hipotecário" (mesma instituicao
        # continua a usar obter_ou_criar_por_instituicao — resolver_por_nome=False por omissão
    # preserva esse comportamento já testado, inalterado.
                        # Conta, misturando o histórico de saldo de dois créditos diferentes (achado do
    # code-reviewer, coberto por
    # test_processar_extratos_pendentes_bbva_dois_contratos_nao_se_fundem).
    if resolver_por_nome:
        conta = await conta_repo.obter_ou_criar_por_nome(
            session,
            titular_id=titular_id,
            instituicao=extrato.instituicao,
            tipo=extrato.tipo_conta,
            nome=extrato.nome_conta,
        )
    else:
        conta = await conta_repo.obter_ou_criar_por_instituicao(
            session,
            titular_id=titular_id,
            instituicao=extrato.instituicao,
            tipo=extrato.tipo_conta,
            nome=extrato.nome_conta,
        )

    # Hierarquia de confiança extrato > ficheiro > manual (spec 2026-08-09, §2.2): se já existe
    # uma âncora nesta data que NÃO veio de um extrato (ficheiro ou manual), o extrato — a fonte
    # de verdade — substitui-a. A colisão é comum, não rara: o ficheiro grava na `Data Mov.` do
    # lançamento mais recente, e o extrato grava na data de fim do período; importar o ficheiro
    # nos primeiros dias do mês para ver a cauda do mês anterior faz as duas coincidirem quase
    # sempre. Sem esta substituição explícita, o `except SaldoDuplicado: pass` abaixo engolia a
    # colisão em silêncio e a âncora do banco nunca chegava a gravar-se (revisão final, achado 2).
    ancora_existente = await saldo_historico_repo.obter_saldo_exato(
        session, conta.id, extrato.saldo_final.data
    )
    if ancora_existente is not None and ancora_existente.origem != "extrato":
        ancora_existente.valor = extrato.saldo_final.valor
        ancora_existente.origem = "extrato"
    else:
        try:
            await saldo_historico_repo.registar_saldo(
                session, conta_id=conta.id, data=extrato.saldo_final.data, valor=extrato.saldo_final.valor
            )
        except SaldoDuplicado:
            # Só chega aqui quando a âncora existente já era de extrato (o ramo acima trata as
            # outras duas origens) — este extrato já foi processado antes. Idempotência: a âncora
            # não é tocada, exatamente como já era antes desta correção.
            pass

    # A guarda é por LINHA e não por documento (spec 2026-08-13). A anterior perguntava "este
    # documento já persistiu esta conta?" e por isso não via o mesmo extrato a chegar dentro de
        # pasta sincronizada e depois por mail.
    #
    # A fotografia é tirada AQUI, antes do ciclo, e isso é a especificação e não uma otimização:
    # `criar_linha` faz flush, por isso uma consulta feita dentro do ciclo veria a linha que o
    # próprio ciclo acabou de criar e saltava a segunda de duas transações iguais no mesmo dia.
    criadas = saltadas = 0
    if movimentos:
        # O limite superior da janela não pode ser só `saldo_final.data`: os parsers de cartão
                # extrato, sem relação estrutural com o período dos movimentos — um movimento com data
        # POSTERIOR ao saldo_final fica fora da fotografia e duplica-se numa segunda ingestão
        # (achado Importante da revisão final, provado empiricamente com uma fixture real de
        # cartão). Usar o máximo entre a última data de movimento e `saldo_final.data` garante que
        # a janela cobre sempre todos os movimentos desta secção.
        ja_existentes = await linha_extrato_repo.contar_existentes_por_chave(
            session,
            conta_id=conta.id,
            de=min(movimento.data for movimento in movimentos),
            ate=max(max(movimento.data for movimento in movimentos), extrato.saldo_final.data),
        )
        vistos: dict[tuple[date, Decimal], int] = {}
        for movimento in movimentos:
            chave = (movimento.data, movimento.valor)
            posicao = vistos.get(chave, 0)
            vistos[chave] = posicao + 1
            if posicao < ja_existentes.get(chave, 0):
                # Esta é uma das M cópias que já existiam antes desta ingestão. As ocorrências
                # a mais (N-M) são transações novas e seguem para criação.
                saltadas += 1
                continue
            await linha_extrato_repo.criar_linha(
                session,
                conta_id=conta.id,
                documento_id=documento.id,
                data=movimento.data,
                valor=movimento.valor,
                descricao=movimento.descricao,
            )
            criadas += 1

    # A-P6: as linhas ignoradas pelo parser nível-0 (garbled, ver banco_generico.py) e os
    # movimentos descartados individualmente por data implausível (ver validar_extrato / Fix 7)
    # são conceptualmente a mesma coisa — "dados que existiam mas não foram persistidos" — por
    # isso partilham o mesmo alerta em vez de duplicar o mecanismo de sinalização.
    total_linhas_ignoradas = extrato.linhas_nao_reconhecidas + linhas_ignoradas_extra
    if total_linhas_ignoradas > 0:
        await alerta_repo.criar_se_novo(
            session,
            tipo="linhas_extrato_ignoradas",
            chave_deduplicacao=f"linhas_extrato_ignoradas:{documento.id}",
            mensagem=(
                f"{total_linhas_ignoradas} linha(s) de movimento não reconhecida(s) ou "
                f"descartada(s) no extrato do documento {documento.id} ({extrato.instituicao} — "
                f"{extrato.nome_conta}); confirme se algum movimento ficou de fora."
            ),
        )

    # Upsert por conta, não append incondicional (achado Importante da revisão final): o mesmo
    # documento é persistido mais que uma vez no fluxo normal (a corrida automática processa as
    # secções que validam, e _aprovar_extrato_manualmente volta a processar TODAS) — um append
    # sem guarda faz um documento de 3 secções reprocessado 2x ficar com 5 entradas, a mesma conta
    # duplicada com números diferentes. A entrada mais RECENTE para uma dada conta substitui a
    # anterior: é o que interessa mostrar num painel de diagnóstico, o estado da última vez que o
    # documento foi processado. Reatribuir o dicionário inteiro (em vez de mutar a lista no sítio)
    # é o que faz o SQLAlchemy reparar na alteração de um JSONB.
    resumo = documento.resumo_ingestao or {"contas": []}
    contas_existentes = [c for c in resumo["contas"] if c["conta"] != extrato.nome_conta]
    documento.resumo_ingestao = {
        "contas": [
            *contas_existentes,
            {"conta": extrato.nome_conta, "criadas": criadas, "saltadas": saltadas},
        ]
    }

    documento.estado_validacao = "validado"


async def _processar_extrato_extraido(
    session: AsyncSession,
    *,
    documento: Documento,
    extrato: ExtratoBancario,
    titular_id: uuid.UUID,
    referencia: date,
    resolver_por_nome: bool = False,
) -> bool:
    try:
        movimentos_validos, movimentos_descartados = validar_extrato(extrato, referencia=referencia)
    except FalhaValidacao:
        # data de saldo implausível, saldo_inicial ausente, ou checksum que não fecha (ver
        # validar_extrato) — todos "tudo ou nada" para o extrato. Um movimento individual com
        # data implausível NÃO chega aqui: já foi filtrado sozinho e não derruba o resto (Fix 7).
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return False

    await _persistir_extrato(
        session,
        documento=documento,
        extrato=extrato,
        movimentos=movimentos_validos,
        titular_id=titular_id,
        linhas_ignoradas_extra=movimentos_descartados,
        resolver_por_nome=resolver_por_nome,
    )
    await session.commit()
    return True


async def processar_extratos_pendentes(
    session: AsyncSession, paperless: PaperlessClient, *, referencia: date
) -> None:
    # A parte "tag -> lista de documentos -> salta já criados -> OCR + atribuição por tags" é
    # idêntica à de faturas.processar_documentos_pendentes e vive em
    # _comum._iterar_documentos_pendentes; `ambito` não é usado neste fluxo (só faturas
    # distingue âmbito comum/pessoal), por isso é ignorado aqui.
    async for paperless_id, texto_ocr, registado_por, _ambito, tag_id in _iterar_documentos_pendentes(
        session, paperless, TAG_EXTRATO_POR_ESTRUTURAR
    ):
        if registado_por is None:
            # sem tag de titular — não há como saber de quem é esta conta (uma `conta` exige
            # titular_id não-nulo), por isso vai direto para revisão manual em vez de adivinhar.
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=0,
                dados_extraidos={},
                estado_validacao="revisao_manual",
            )
            await _alertar_revisao_manual(session, documento)
            await session.commit()
            # Fix 6: remove a tag mesmo sem titular. Já triámos este documento (foi para
            # revisao_manual, com alerta ativo) — sem remover a tag, o paperless continuaria a
            # listá-lo como "por estruturar" para sempre, uma bandeira desatualizada e enganosa
            # sobre o estado real do documento (que já não está pendente de estruturação, está
            # pendente de um titular). Nota: não há dados extraídos para este caso (dados_extraidos
            # fica {}), por isso — tal como o equivalente já existente para faturas nível1 sem
            # validação bem-sucedida — este documento específico ainda não é resolvível via
            # aprovar_documento_manualmente; resolvê-lo exigiria reobter o texto do paperless e
            # atribuir um titular manualmente, o que fica fora do âmbito deste batch.
            await paperless.remover_tag(paperless_id, tag_id=tag_id)
            continue

        extrato_nivel0 = parse_banco_generico(texto_ocr)
        extratos_bpi = []
        None = None
        None = None
        None = None
        if extrato_nivel0 is None and not extratos_bpi:
                        # banco_generico.py — reaproveita o MESMO caminho de conta única abaixo (não o
                                    # registar saldo, sem lista de movimentos). `None` fica guardado à parte (em
                        # resolver_por_nome não depender de inspecionar o conteúdo do extrato — só da
            # proveniência real do parser.
            None = None
            extrato_nivel0 = None
        if extrato_nivel0 is None and not extratos_bpi:
                                    # parsers dedicados de conta única não importa em termos de correção — nenhum
            # documento real casa com mais que uma âncora — mas mantém-se estável e explícita).
            # `None` fica guardado à parte pela MESMA razão que `None`
            # acima: resolver_por_nome não deve depender de inspecionar o conteúdo do extrato.
            None = None
            extrato_nivel0 = None
        if extrato_nivel0 is None and not extratos_bpi:
                                                # guardado à parte pela MESMA razão que `None`/`None`:
            # resolver_por_nome não deve depender de inspecionar o conteúdo do extrato.
            None = None
            extrato_nivel0 = None
        if extrato_nivel0 is None and not extratos_bpi:
            # Trade Republic (conta cash): também documento de uma só conta (ver
                        # nota sobre ordem estável mas irrelevante para a correção, ver acima).
            None = None
            extrato_nivel0 = None

        if extrato_nivel0 is not None:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=0,
                dados_extraidos=extrato_nivel0.model_dump(mode="json"),
                registado_por=registado_por,
            )
            validado = await _processar_extrato_extraido(
                session,
                documento=documento,
                extrato=extrato_nivel0,
                titular_id=registado_por,
                referencia=referencia,
                                # tipo_conta="divida" são iguais para QUALQUER contrato de crédito automóvel
                                # exatamente a mesma armadilha já resolvida para as duas secções de crédito do
                                # obter_ou_criar_por_instituicao (que combina só por titular_id+instituicao+tipo,
                                # Conta, misturando o histórico de saldo de dois créditos diferentes. A MESMA
                                # "divida" são iguais para qualquer conta-cartão (só nome_conta varia, com o
                                # None também força resolver_por_nome=True. Idem para o Cartão
                                                                resolver_por_nome=(
                    None is not None
                    or None is not None
                    or None is not None
                ),
            )
            if validado:
                await paperless.remover_tag(paperless_id, tag_id=tag_id)
                await reconciliar_linhas_pendentes(session)
        elif extratos_bpi:
                        # documento — um só `Documento` é criado (dados_extraidos guarda a lista completa),
            # mas cada secção é persistida separadamente via _processar_extrato_extraido
            # (resolver_por_nome=True: ver nota em _persistir_extrato sobre a armadilha de
            # obter_ou_criar_por_instituicao fundir as duas contas de crédito).
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=0,
                dados_extraidos={"contas": [extrato.model_dump(mode="json") for extrato in extratos_bpi]},
                registado_por=registado_por,
            )
            todas_validadas = True
            for extrato_bpi in extratos_bpi:
                validado = await _processar_extrato_extraido(
                    session,
                    documento=documento,
                    extrato=extrato_bpi,
                    titular_id=registado_por,
                    referencia=referencia,
                    resolver_por_nome=True,
                )
                todas_validadas = todas_validadas and validado
            if not todas_validadas:
                # Achado Importante (revisão Tarefa 10): documento.estado_validacao é escrito
                # incondicionalmente por _processar_extrato_extraido a cada secção — sem este
                # passo, a ÚLTIMA secção processada decidiria sozinha o estado final do
                # documento (ex.: secção 3 falha e dispara o alerta, mas secção 4 valida e
                # reescreve "validado" por cima, mesmo sem secção 3 ter persistido
                # linha_extrato/saldo_historico). Força explicitamente "revisao_manual" quando
                # pelo menos uma secção falhou — não repete o alerta, que já foi disparado por
                # _alertar_revisao_manual (idempotente via chave_deduplicacao).
                documento.estado_validacao = "revisao_manual"
                await session.commit()
            if todas_validadas:
                await paperless.remover_tag(paperless_id, tag_id=tag_id)
                await reconciliar_linhas_pendentes(session)
        else:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=1,
                dados_extraidos={},
                registado_por=registado_por,
            )
            await fila_repo.criar_item(
                session, documento_id=documento.id, texto_ocr=texto_ocr, tipo="extrato_bancario"
            )
            await session.commit()


async def finalizar_extrato_nivel1(
    session: AsyncSession, *, item_id: uuid.UUID, paperless: PaperlessClient, referencia: date
) -> None:
    # cabeçalho (fetch do item concluído + resolução/orfandade do documento) partilhado com
    # finalizar_documento_nivel1 — ver _comum._obter_item_concluido_com_documento.
    resultado = await _obter_item_concluido_com_documento(session, item_id)
    if resultado is None:
        return
    item, documento = resultado

    if documento.registado_por is None:
        # sem titular associado ao documento não há como criar a conta (Conta.titular_id não é
        # nulo) nem atribuir os movimentos — genuinamente não processável sem intervenção humana.
        await fila_repo.marcar_erro(
            session, item_id, "extrato bancário sem titular associado (documento sem registado_por)"
        )
        await session.commit()
        return

    if documento.estado_validacao == "validado":
        # já finalizado noutra corrida — idempotência (A2), mesmo padrão que
        # finalizar_documento_nivel1: sem este guard, um retry duplicaria linhas em
        # linha_extrato (que, ao contrário de saldo_historico, não tem unique constraint).
        return

    try:
        extrato = ExtratoBancario.model_validate(item.resultado_json)
    except ValidationError:
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return

    documento.dados_extraidos = extrato.model_dump(mode="json")

    validado = await _processar_extrato_extraido(
        session,
        documento=documento,
        extrato=extrato,
        titular_id=documento.registado_por,
        referencia=referencia,
    )
    if validado:
        tag_id = await paperless.obter_id_de_tag(TAG_EXTRATO_POR_ESTRUTURAR)
        await paperless.remover_tag(documento.paperless_document_id, tag_id=tag_id)
        await reconciliar_linhas_pendentes(session)


async def _aprovar_extrato_manualmente(
    session: AsyncSession, *, documento: Documento, paperless: PaperlessClient
) -> bool:
    dados = documento.dados_extraidos
        # processar_extratos_pendentes) guarda dados_extraidos como {"contas": [...]} em vez de um
    # ExtratoBancario único — ExtratoBancario.model_validate(dados) levantava sempre
    # ValidationError para este formato, e a aprovação manual devolvia False em silêncio para
        eh_multiconta = isinstance(dados, dict) and isinstance(dados.get("contas"), list)

    if eh_multiconta:
        extratos: list[ExtratoBancario] = []
        for item in dados["contas"]:
            try:
                extratos.append(ExtratoBancario.model_validate(item))
            except ValidationError:
                # um item malformado individual não deve impedir as restantes contas de serem
                # aprovadas — mesma convenção de A-P6 (falha isolada não derruba o resto).
                continue
        if not extratos:
            # dados_extraidos vazio ou nenhuma conta reconhecível — não há dados capturados
            # para aprovar (mesma limitação já existente para faturas nível1 equivalentes).
            return False
    else:
        try:
            extratos = [ExtratoBancario.model_validate(dados)]
        except ValidationError:
            # dados_extraidos vazio ou incompatível com ambos os schemas (ex.: um extrato nível-1
            # cujo LLM nunca conseguiu estruturar nada, ou o documento "sem tag de titular" de
            # processar_extratos_pendentes) — não há dados capturados para aprovar. Mesma limitação
            # já existente para faturas nível1 equivalentes (dados_extraidos == {}); fora do âmbito
            # deste batch (exigiria reobter o texto do paperless).
            return False

    if documento.registado_por is None:
        # sem titular associado não há como criar a `conta` (titular_id não é opcional) — este
        # caso também já não tinha dados suficientes para o schema (ver acima), mas fica explícito.
        return False

    # Aprovação manual é uma decisão humana que substitui o portão automático: tal como
    # aprovar_documento_manualmente (pipeline/aprovacao.py) ignora validar_fatura de propósito
    # para faturas, aqui ignora-se validar_extrato — o humano já reviu o documento e confirma
    # que deve ser persistido. resolver_por_nome=True no caminho multi-conta pelo mesmo motivo
    # que o ciclo principal de processar_extratos_pendentes usa (ver _persistir_extrato):
    # obter_ou_criar_por_instituicao fundiria contas de crédito diferentes da mesma instituição.
    #
    # NOTA: para o caminho de conta única (resolver_por_nome=False), a ambiguidade de 2+ contas
            # corrigido diretamente em obter_ou_criar_por_instituicao (conta_repo.py), que agora só
    # recorre ao nome quando já há mais que uma conta candidata, em vez de forçar
    # resolver_por_nome=True aqui incondicionalmente (o que criaria uma conta duplicada sempre
    # que o nome extraído do extrato variasse ligeiramente do nome já guardado).
    for extrato in extratos:
        await _persistir_extrato(
            session,
            documento=documento,
            extrato=extrato,
            movimentos=extrato.movimentos,
            titular_id=documento.registado_por,
            resolver_por_nome=eh_multiconta,
        )

    if eh_multiconta and len(extratos) < len(dados["contas"]):
        # nem todas as contas do documento validaram contra o schema — _persistir_extrato marca
        # "validado" incondicionalmente a cada chamada (mesma armadilha do ciclo principal, ver
        # processar_extratos_pendentes); força "revisao_manual" explicitamente em vez de deixar a
        # última conta persistida com sucesso mentir sobre o resultado agregado.
        documento.estado_validacao = "revisao_manual"
    await session.commit()

    tag_id = await paperless.obter_id_de_tag(TAG_EXTRATO_POR_ESTRUTURAR)
    await paperless.remover_tag(documento.paperless_document_id, tag_id=tag_id)
    await reconciliar_linhas_pendentes(session)
    return True
