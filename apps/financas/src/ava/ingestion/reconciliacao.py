import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.categorizacao_automatica import padrao_de_descricao
from ava.ingestion.casamento import casar_linha
from ava.models.linha_extrato import LinhaExtrato
from ava.repositories import alerta_repo, categoria_repo, conta_repo, linha_extrato_repo, movimento_repo

JANELA_DIAS = 5

# (tipo, origem, tipo de alerta, texto) — uma tabela em vez de duas funções quase iguais
_INVERSOS = (
    ("saida", "documento", "movimento_sem_extrato", "A despesa de {valor}€ em {data} nunca foi debitada"),
    ("entrada", "regra", "rendimento_sem_extrato", "O rendimento de {valor}€ em {data} nunca foi creditado"),
    # Faltava esta linha (achado de 2026-08-20): uma despesa recorrente (Recorrente, tipo="saida")
    # tinha exatamente a mesma exposição que "documento" acima -- um movimento "regra" nunca
    # ligado ao extrato, sem ninguém a avisar. Mesmo `tipo_alerta` que a linha "documento": é o
    # mesmo alerta ao utilizador ("esta despesa nunca foi debitada"), só muda de onde o movimento
    # veio -- não há nenhum sítio no código que distinga por `tipo_alerta`, só a chave de
    # deduplicação (que já inclui `movimento.id`, por isso não há colisão entre as duas origens).
    ("saida", "regra", "movimento_sem_extrato", "A despesa de {valor}€ em {data} nunca foi debitada"),
)

# Texto literal que _MOVIMENTO_AMORTIZACAO (banco_bpi.py) sempre devolve como descrição do lado
# da conta de dívida — sem número de contrato, sem dígito nenhum. O lado da conta à ordem tem o
# mesmo prefixo mas com o número de contrato embutido a seguir (ver _parse_secao_a_ordem).
_PREFIXO_AMORTIZACAO = "AMORTIZACAO DE CAPITAL"


async def conciliar_amortizacoes_de_credito(session: AsyncSession) -> None:
    """Liga o pagamento de uma prestação de crédito às DUAS linhas de extrato pendentes que o
    mesmo evento real produz: uma na conta de dívida ("AMORTIZACAO DE CAPITAL", sem número de
    contrato) e outra na conta à ordem que debitou o pagamento ("AMORTIZACAO DE CAPITAL -
    <contrato>", com o contrato embutido — ver banco_bpi.py), na mesma data e com o mesmo valor
    absoluto. Sem isto, seriam tratadas como dois eventos financeiros independentes: a amortização
    exigiria categorização manual na conta de dívida, e o débito na conta à ordem apareceria como
    uma "despesa" a repetir a mesma informação.

    Cria um Movimento tipo="transferencia" (conta à ordem → conta de dívida) por par encontrado,
    já com a categoria "Pagamento de crédito" atribuída (ver categorias_iniciais.py, grupo
    "Encargos financeiros") — não faz sentido pedir ao utilizador para escolher categoria numa
    transferência cujo destino já diz tudo (uma conta tipo="divida"). Se essa categoria ainda não
    existir (ex. sementeira/migração não corrida), cai no comportamento anterior: cria sem
    categoria, fica em dashboard.py /movimentos, secção de transferências por categorizar.
    Os juros e o imposto do selo, que também são debitados na conta à ordem no mesmo dia, ficam
    de fora deste par de propósito — continuam despesas normais e separadas (ver docstring de
    _parse_secao_credito em banco_bpi.py: só a amortização de capital reduz o capital em dívida).

    Zero ou vários candidatos em qualquer dos lados: nunca adivinha (mesmo princípio de
    conciliar_uma_linha) — a linha fica pendente para o caminho normal de reconciliação/revisão
    manual tratar sozinha.

    Considera tanto "pendente" (o caso comum: ambas as linhas do mesmo evento chegam na mesma
    corrida de ingestão) como "revisao_manual" (uma importação histórica em bloco, sem esta
    função ainda existir na altura, já passou as duas linhas pelo caminho normal sem candidato —
    ficaram à espera na fila de revisão manual em vez de nunca mais serem reconsideradas).
    """
    pendentes = await linha_extrato_repo.listar_pendentes(session)
    pendentes += await linha_extrato_repo.listar_em_revisao_manual(session)
    candidatos_credito = [linha for linha in pendentes if linha.descricao == _PREFIXO_AMORTIZACAO]
    if not candidatos_credito:
        return

    candidatos_a_ordem = [
        linha
        for linha in pendentes
        if linha.descricao.startswith(_PREFIXO_AMORTIZACAO) and linha.descricao != _PREFIXO_AMORTIZACAO
    ]

    categoria_pagamento_credito = await categoria_repo.obter_por_nomes(
        session, grupo="Encargos financeiros", nome="Pagamento de crédito"
    )
    categoria_id = categoria_pagamento_credito.id if categoria_pagamento_credito else None

    for linha_credito in candidatos_credito:
        conta_credito = await conta_repo.obter_por_id(session, linha_credito.conta_id)
        if conta_credito is None or conta_credito.tipo != "divida":
            continue

        correspondentes = [
            linha_ordem
            for linha_ordem in candidatos_a_ordem
            if linha_ordem.data == linha_credito.data and abs(linha_ordem.valor) == abs(linha_credito.valor)
        ]
        if len(correspondentes) != 1:
            continue
        linha_a_ordem = correspondentes[0]
        conta_a_ordem = await conta_repo.obter_por_id(session, linha_a_ordem.conta_id)
        if conta_a_ordem is None or conta_a_ordem.tipo != "a_ordem":
            continue

        await movimento_repo.criar_movimento(
            session,
            tipo="transferencia",
            valor=abs(linha_credito.valor),
            data=linha_credito.data,
            origem="extrato",
            descricao="Amortização de capital",
            conta_id=conta_a_ordem.id,
            conta_destino_id=conta_credito.id,
            linha_extrato_id=linha_a_ordem.id,
            linha_extrato_destino_id=linha_credito.id,
            linhas=[movimento_repo.LinhaNova(valor=abs(linha_credito.valor), categoria_id=categoria_id)],
        )
        await linha_extrato_repo.marcar_conciliada_sem_ligar(session, linha_a_ordem.id)
        await linha_extrato_repo.marcar_conciliada_sem_ligar(session, linha_credito.id)
        # tirada dos candidatos disponíveis — não pode ser reaproveitada por outro par nesta
        # mesma corrida (ex. duas contas de crédito com amortização coincidentemente na mesma
        # data e valor, disputando a mesma linha da conta à ordem).
        candidatos_a_ordem.remove(linha_a_ordem)


async def conciliar_uma_linha(session: AsyncSession, linha: LinhaExtrato) -> None:
    # Primeiro: será que esta linha já está no razão, registada à mão pelo utilizador? Se sim,
    # confirma-se o movimento existente em vez de criar um segundo (spec 2026-08-08, §6). Tem de
    # vir antes de tudo o resto: criar o movimento primeiro e casar depois seria contá-lo duas
    # vezes no intervalo entre as duas coisas.
    if await casar_linha(session, linha):
        return

    tipo = "saida" if linha.valor < 0 else "entrada"
    candidatos = await movimento_repo.listar_candidatos_para_conciliar(
        session, tipo=tipo, valor=abs(linha.valor), data=linha.data, janela_dias=JANELA_DIAS
    )
    # Desde que casar_linha (acima) passa a correr primeiro, este ramo já não apanha o caso comum
    # — um movimento manual do utilizador na MESMA conta, valor e data: esse já ficou resolvido
    # ali. O que sobra aqui é mais estreito: listar_candidatos_para_conciliar é CEGA à conta (não
    # filtra por conta_id nenhum), por isso só chegam candidatos aqui quando o movimento não tem
    # conta (ex. a fatura da EDP, sem conta associada) ou pertence a OUTRA conta que coincide em
    # tipo/valor/data. Continua a ser este ramo que reconcilia a fatura da EDP sem conta — não é
    # código morto, mesmo com âmbito mais estreito do que antes.
    if len(candidatos) == 1:
        await linha_extrato_repo.marcar_conciliada(session, linha.id, candidatos[0].id)
        return

    # Antes de desistir para revisão manual, tenta a categoria já usada da última vez que uma
    # linha DESTA MESMA CONTA com o mesmo padrão de descrição (mesmo comerciante, número de
    # referência diferente — ver categorizacao_automatica.padrao_de_descricao) foi categorizada
    # manualmente. Isto é o que faz uma transação recorrente (ex. o mesmo supermercado todos os
    # meses) deixar de precisar de categorização manual depois da primeira vez.
    #
    # Guard de valor zero ANTES de tentar o padrão aprendido (mesmo motivo do Achado 3 em
    # _resolver): criar_movimento rejeita valor<=0 com ValorNaoPositivo, e esta função corre num
    # loop sem try/except em reconciliar_linhas_pendentes — sem este guard, uma linha de valor
    # zero (ex. um estorno exato) cujo padrão coincidisse com um já aprendido rebentaria o batch
    # inteiro em vez de só esta linha.
    if abs(linha.valor) != 0:
        padrao = padrao_de_descricao(linha.descricao)
        categoria_id = await movimento_repo.obter_categoria_mais_recente_por_padrao(
            session, tipo=tipo, padrao=padrao, conta_id=linha.conta_id
        )
        if categoria_id is not None:
            await _criar_movimento_categorizado(session, linha=linha, categoria_id=categoria_id, tipo=tipo)
            return

    # zero ou vários candidatos, e nenhuma categoria aprendida — nunca adivinha (spec §3.2 do
    # design de património)
    await linha_extrato_repo.marcar_revisao_manual(session, linha.id)


async def reconciliar_linhas_pendentes(session: AsyncSession) -> None:
    # Primeiro os pares de amortização de crédito (ver conciliar_amortizacoes_de_credito) — depois
    # de emparelhadas, as duas linhas deixam de estar "pendente" e o loop abaixo não as vê mais.
    await conciliar_amortizacoes_de_credito(session)
    for linha in await linha_extrato_repo.listar_pendentes(session):
        await conciliar_uma_linha(session, linha)
    await session.commit()


async def _criar_movimento_categorizado(
    session: AsyncSession, *, linha: LinhaExtrato, categoria_id: uuid.UUID, tipo: str,
    ativo_id: uuid.UUID | None = None,
    conta_relacionada_id: uuid.UUID | None = None,
    leitura_odometro: int | None = None,
    quantidade: Decimal | None = None,
) -> None:
    conta = await conta_repo.obter_por_id(session, linha.conta_id)
    movimento = await movimento_repo.criar_movimento(
        session,
        tipo=tipo,
        # abs(): linha_extrato.valor tem sinal, movimento.valor é sempre positivo
        valor=abs(linha.valor),
        data=linha.data,
        origem="extrato",
        descricao=linha.descricao,
        conta_id=linha.conta_id,
        titular_id=conta.titular_id if conta is not None else None,
        linhas=[movimento_repo.LinhaNova(
            valor=abs(linha.valor), categoria_id=categoria_id,
            ativo_id=ativo_id, conta_relacionada_id=conta_relacionada_id, leitura_odometro=leitura_odometro,
            quantidade=quantidade, unidade="L" if quantidade else None
        )],
    )
    await linha_extrato_repo.marcar_conciliada(session, linha.id, movimento.id)


async def _resolver(
    session: AsyncSession, *, linha_id: uuid.UUID, categoria_id: uuid.UUID, tipo: str,
    ativo_id: uuid.UUID | None = None,
    conta_relacionada_id: uuid.UUID | None = None,
    leitura_odometro: int | None = None,
    quantidade: Decimal | None = None,
) -> bool:
    linha = await linha_extrato_repo.obter_por_id(session, linha_id)
    if linha is None or linha.estado != "revisao_manual":
        return False

    # Achado 3 (revisão final de fecho da Fase A): uma linha_extrato de valor 0,00 (rara, mas
    # possível — ex. um estorno que anula exatamente o original) faria criar_movimento levantar
    # ValorNaoPositivo mais abaixo, rebentando a rota /movimentos com um 500. Um movimento de
    # valor zero não tem significado financeiro real; resolver como despesa/rendimento não é a
    # ação certa aqui — a ação correta para o utilizador é "Ignorar" (ignorar_linha), que já existe
    # e já funciona. Mesmo padrão de devolver False já usado acima quando a linha não está em
    # revisao_manual.
    if abs(linha.valor) == 0:
        return False

    await _criar_movimento_categorizado(
        session, linha=linha, categoria_id=categoria_id, tipo=tipo,
        ativo_id=ativo_id, conta_relacionada_id=conta_relacionada_id,
        leitura_odometro=leitura_odometro, quantidade=quantidade
    )

    await session.commit()
    return True


async def resolver_como_despesa(
    session: AsyncSession, *, linha_id: uuid.UUID, categoria_id: uuid.UUID,
    ativo_id: uuid.UUID | None = None,
    conta_relacionada_id: uuid.UUID | None = None,
    leitura_odometro: int | None = None,
    quantidade: Decimal | None = None,
) -> bool:
    return await _resolver(
        session, linha_id=linha_id, categoria_id=categoria_id, tipo="saida",
        ativo_id=ativo_id, conta_relacionada_id=conta_relacionada_id, 
        leitura_odometro=leitura_odometro, quantidade=quantidade
    )


async def resolver_como_rendimento(
    session: AsyncSession, *, linha_id: uuid.UUID, categoria_id: uuid.UUID,
    ativo_id: uuid.UUID | None = None
) -> bool:
    return await _resolver(session, linha_id=linha_id, categoria_id=categoria_id, tipo="entrada", ativo_id=ativo_id)


async def resolver_como_transferencia(
    session: AsyncSession, *, linha_id: uuid.UUID, conta_relacionada_id: uuid.UUID
) -> bool:
    linha = await linha_extrato_repo.obter_por_id(session, linha_id)
    if linha is None or linha.estado != "revisao_manual":
        return False
    if abs(linha.valor) == 0:
        return False

    # Transferência adiantamento/pagamento:
    # Se a linha é entrada (valor > 0), o dinheiro veio da conta_relacionada para esta conta.
    # Se a linha é saída (valor < 0), o dinheiro foi desta conta para a conta_relacionada.
    if linha.valor > 0:
        conta_id = conta_relacionada_id
        conta_destino_id = linha.conta_id
    else:
        conta_id = linha.conta_id
        conta_destino_id = conta_relacionada_id

    movimento = await movimento_repo.criar_movimento(
        session,
        tipo="transferencia",
        valor=abs(linha.valor),
        data=linha.data,
        origem="extrato",
        descricao=linha.descricao,
        conta_id=conta_id,
        conta_destino_id=conta_destino_id,
        linha_extrato_id=linha.id if linha.valor < 0 else None,
        linha_extrato_destino_id=linha.id if linha.valor > 0 else None,
        linhas=[movimento_repo.LinhaNova(valor=abs(linha.valor), categoria_id=None)],
    )
    await linha_extrato_repo.marcar_conciliada(session, linha.id, movimento.id)
    await session.commit()
    return True


async def categorizar_transferencia(
    session: AsyncSession, *, movimento_id: uuid.UUID, categoria_id: uuid.UUID
) -> bool:
    """Atribui uma categoria a uma transferência de amortização de crédito (ver
    conciliar_amortizacoes_de_credito) e aplica a MESMA categoria a todas as outras
    transferências ainda por categorizar PARA A MESMA conta de destino. Continua a agrupar,
    ao contrário de _resolver (que deixou de agrupar por descrição — ver a spec
    2026-08-06-movimentos-individuais-design.md, §4.6), porque agrupar por conta de destino não é
    ambíguo: o destino é sempre a mesma conta de crédito, por isso todas as suas amortizações
    partilham naturalmente a mesma categoria (ex. "Amortização Mortgage & Loans").
    """
    movimento = await movimento_repo.obter_por_id(session, movimento_id)
    if movimento is None or movimento.tipo != "transferencia" or not movimento.linhas:
        return False
    if movimento.linhas[0].categoria_id is not None:
        return False

    movimento.linhas[0].categoria_id = categoria_id

    desc_upper = movimento.descricao.upper() if movimento.descricao else ""
    if "AMORTIZACAO" in desc_upper or "JUROS" in desc_upper or "PRESTACAO" in desc_upper:
        chave_grupo_original = movimento.conta_destino_id or f"sem_destino_{movimento.descricao}"
    else:
        chave_grupo_original = movimento.conta_destino_id or f"sem_destino_{padrao_de_descricao(movimento.descricao)}"

    for outro in await movimento_repo.listar_transferencias_sem_categoria(session):
        if outro.id == movimento.id or not outro.linhas:
            continue
            
        outro_desc_upper = outro.descricao.upper() if outro.descricao else ""
        if "AMORTIZACAO" in outro_desc_upper or "JUROS" in outro_desc_upper or "PRESTACAO" in outro_desc_upper:
            chave_grupo_outro = outro.conta_destino_id or f"sem_destino_{outro.descricao}"
        else:
            chave_grupo_outro = outro.conta_destino_id or f"sem_destino_{padrao_de_descricao(outro.descricao)}"
            
        if chave_grupo_outro == chave_grupo_original:
            outro.linhas[0].categoria_id = categoria_id

    await session.commit()
    return True


async def desfazer_movimento(session: AsyncSession, *, movimento_id: uuid.UUID) -> bool:
    """Desfaz uma categorização errada:
    - Se o movimento teve origem num extrato (linha_extrato_id preenchido), apaga o movimento
      e devolve a(s) linha(s) de extrato a 'revisao_manual', para o utilizador as poder recategorizar
      em /movimentos.
    - Se o movimento tem origem categorizável (ficheiro, manual, telegram, web) sem linha_extrato_id,
      NÃO apaga o movimento: limpa as categorias das suas linhas (categoria_id=None), fazendo-o
      voltar a aparecer na lista de /movimentos por categorizar, preservando a transação.
    - Um movimento gerado por regra sem extrato é apagado.
    """
    movimento = await movimento_repo.obter_por_id(session, movimento_id)
    if movimento is None:
        return False

    if movimento.linha_extrato_id is not None:
        await linha_extrato_repo.marcar_revisao_manual(session, movimento.linha_extrato_id)
    if movimento.linha_extrato_destino_id is not None:
        await linha_extrato_repo.marcar_revisao_manual(session, movimento.linha_extrato_destino_id)

    if movimento.linha_extrato_id is not None or movimento.linha_extrato_destino_id is not None:
        await movimento_repo.apagar(session, movimento)
    elif movimento.origem in movimento_repo.ORIGENS_CATEGORIZAVEIS:
        for linha in movimento.linhas:
            linha.categoria_id = None
            linha.ativo_id = None
            linha.conta_relacionada_id = None
    else:
        await movimento_repo.apagar(session, movimento)

    await session.commit()
    return True


async def ignorar_linha(session: AsyncSession, *, linha_id: uuid.UUID) -> bool:
    linha = await linha_extrato_repo.obter_por_id(session, linha_id)
    if linha is None or linha.estado != "revisao_manual":
        return False

    await linha_extrato_repo.marcar_ignorado(session, linha_id)
    await session.commit()
    return True


async def verificar_movimentos_sem_extrato(
    session: AsyncSession, *, referencia: date, prazo_dias: int = 10
) -> list[str]:
    limite = referencia - timedelta(days=prazo_dias)
    novas_chaves: list[str] = []

    for tipo, origem, tipo_alerta, texto in _INVERSOS:
        for movimento in await movimento_repo.listar_sem_linha_extrato(
            session, tipo=tipo, limite_data=limite, origem=origem
        ):
            chave = f"{tipo_alerta}:{movimento.id}"
            alerta = await alerta_repo.criar_se_novo(
                session,
                tipo=tipo_alerta,
                chave_deduplicacao=chave,
                mensagem=texto.format(valor=movimento.valor, data=movimento.data),
            )
            if alerta is not None:
                novas_chaves.append(chave)

    await session.commit()
    return novas_chaves
