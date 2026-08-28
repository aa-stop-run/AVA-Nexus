from ava.extraction.parsers.generic_invoice import parse_generic_invoice
"""Fluxo de ingestão de faturas de fornecedores (documentos paperless)."""

import uuid
from datetime import date, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.extraction import validadores
from ava.extraction.schema import FaturaExtraida
from ava.financas.saldos import JANELA_CASAMENTO_DIAS
from ava.ingestion.pipeline._comum import (
    FalhaValidacao,
    _alertar_revisao_manual,
    _iterar_documentos_pendentes,
    _obter_item_concluido_com_documento,
)
from ava.integrations.paperless import PaperlessClient
from ava.models.documento import Documento
from ava.models.movimento import Movimento
from ava.repositories import (
    ativo_repo,
    categoria_repo,
    documento_repo,
    fila_repo,
    fornecedor_repo,
    movimento_repo,
)

TAG_POR_ESTRUTURAR = "por-estruturar"
PARSERS_NIVEL0 = (parse_generic_invoice,)

# Origens com evidência bancária real, na direção inversa de casamento.ORIGENS_POR_CONFIRMAR:
# lá, um "documento" nunca confirma uma linha de extrato (protege o alerta "nunca foi debitada"
# de um casamento coincidente); aqui, o mesmo cuidado aplica-se ao contrário -- uma fatura nunca
# deve gerar um segundo movimento quando o banco já registou este pagamento.
_ORIGENS_BANCARIAS = movimento_repo.ORIGENS_REGISTO_MANUAL + ("ficheiro", "extrato")


def _inferir_tipo_fornecedor(fatura: FaturaExtraida) -> str:
    if fatura.consumo is None:
        return "outro"
    return "eletricidade" if fatura.consumo.unidade == "kWh" else "agua"


async def validar_fatura(
    session: AsyncSession, fatura: FaturaExtraida, *, fornecedor_id: uuid.UUID, referencia: date
) -> None:
    # Achado 3 (revisão final de fecho da Fase A): FaturaExtraida.valor_total não tem constraint
    # de schema (Decimal livre), e movimento_repo.criar_movimento só rejeita valor <= 0 no último
    # nível de defesa, dentro de _persistir_fatura — tarde de mais para o caminho automático
    # (nível-0/nível-1, via _processar_fatura_extraida): a exceção subiria sem tratamento pelo job
    # agendado job_ingestao, que não tem nenhum try/except geral. Mesmo mecanismo já usado para
    # data implausível, NIF, IBAN e magnitude histórica: FalhaValidacao encaminha corretamente
    # para revisao_manual + alerta ativo em vez de rebentar o ciclo de ingestão inteiro.
    if fatura.valor_total <= 0:
        raise FalhaValidacao(f"valor total não positivo: {fatura.valor_total}")

    if fatura.linhas:
        valores = [linha.valor for linha in fatura.linhas]
        if not validadores.soma_linhas_igual_total(valores, fatura.valor_total):
            raise FalhaValidacao("soma das linhas não bate com o total")

    if fatura.nif_emissor and not validadores.nif_valido(fatura.nif_emissor):
        raise FalhaValidacao(f"NIF inválido: {fatura.nif_emissor}")

    if fatura.iban and not validadores.iban_valido(fatura.iban):
        raise FalhaValidacao(f"IBAN inválido: {fatura.iban}")

    # margem alargada: uma data-limite de pagamento é naturalmente futura (15-30 dias comuns)
    if not validadores.data_plausivel(fatura.data_limite_pagamento, referencia, margem_futura_dias=60):
        raise FalhaValidacao(f"data limite implausível: {fatura.data_limite_pagamento}")

    historico = await movimento_repo.historico_valores_fornecedor(session, fornecedor_id)
    if not validadores.valor_dentro_magnitude_historica(fatura.valor_total, historico):
        raise FalhaValidacao(f"valor {fatura.valor_total} foge muito do histórico do fornecedor")


# O tipo do fornecedor (inferido da unidade de consumo da fatura) resolve-se para uma categoria
# do conjunto inicial. É o único ponto onde o pipeline de faturas escolhe categoria; tudo o resto
# é decisão humana ou de regra (A-P4).
_CATEGORIA_POR_TIPO_FORNECEDOR: dict[str, tuple[str, str]] = {
    "eletricidade": ("Habitação", "Eletricidade"),
    "agua": ("Habitação", "Água"),
    "outro": ("Outros", "Não classificado"),
}


async def _resolver_categoria_da_fatura(
    session: AsyncSession, tipo_fornecedor: str
) -> uuid.UUID | None:
    grupo, nome = _CATEGORIA_POR_TIPO_FORNECEDOR.get(
        tipo_fornecedor, _CATEGORIA_POR_TIPO_FORNECEDOR["outro"]
    )
    categoria = await categoria_repo.obter_por_nomes(session, grupo=grupo, nome=nome)
    # None é aceitável: a linha fica por categorizar e aparece destacada no ledger. Preferível a
    # inventar uma categoria (A-P4).
    return categoria.id if categoria is not None else None


async def _movimento_bancario_compativel(
    session: AsyncSession, *, fatura: FaturaExtraida, titular_id: uuid.UUID | None
) -> Movimento | None:
    """Um movimento já visto pelo banco (manual/ficheiro/extrato) que seja este mesmo pagamento.

    Sem isto, uma fatura processada DEPOIS de o banco já ter registado o pagamento (a ordem
    inversa da mais comum) duplicava a despesa: um movimento "documento" novo a somar-se ao que
    já existia (achado de 2026-08-20, pagamento EDP de 83,39€ em 2026-08-07). Mesma janela e
    mesma lógica de valor exato de `importacao_ficheiro._compativel` e `casamento.casar_linha` --
    nunca por descrição, sempre por valor+data (as fontes fraseiam o mesmo pagamento de formas
    diferentes).

    Restrito ao `titular_id` da fatura: numa casa com mais de um titular, uma coincidência de
    valor/data do OUTRO titular não pode ser confundida com este pagamento -- ligaria o
    fornecedor/documento a um movimento errado e apagaria o alerta "nunca foi debitada" para uma
    fatura que pode continuar genuinamente por pagar.

    `fornecedor_id.is_(None)`: um movimento já reclamado por outra fatura não é candidato outra
    vez -- a mesma proteção de idempotência que `_compativel` dá via `linha_extrato_id.is_(None)`.
    """
    inicio = fatura.data_limite_pagamento - timedelta(days=JANELA_CASAMENTO_DIAS)
    fim = fatura.data_limite_pagamento + timedelta(days=JANELA_CASAMENTO_DIAS)
    resultado = await session.execute(
        select(Movimento).where(
            Movimento.origem.in_(_ORIGENS_BANCARIAS),
            Movimento.tipo == "saida",
            Movimento.valor == fatura.valor_total,
            Movimento.data >= inicio,
            Movimento.data <= fim,
            Movimento.titular_id == titular_id,
            Movimento.fornecedor_id.is_(None),
        ).order_by(Movimento.data, Movimento.id)
    )
    candidatos = list(resultado.scalars().all())
    if not candidatos:
        return None
    candidatos.sort(
        key=lambda m: (abs((m.data - fatura.data_limite_pagamento).days), m.data, m.id)
    )
    return candidatos[0]


async def _persistir_fatura(
    session: AsyncSession,
    *,
    documento: Documento,
    fatura: FaturaExtraida,
    fornecedor_id: uuid.UUID,
    tipo_fornecedor: str,
) -> None:
    existente = await _movimento_bancario_compativel(
        session, fatura=fatura, titular_id=documento.registado_por
    )
    if existente is not None:
        existente.fornecedor_id = fornecedor_id
        existente.documento_id = documento.id
        documento.estado_validacao = "validado"
        return

    categoria_id = await _resolver_categoria_da_fatura(session, tipo_fornecedor)

    ativo_id = None
    if fatura.ativo_relacionado:
        ativo_obj = await ativo_repo.obter_por_nome_aproximado(session, fatura.ativo_relacionado)
        if ativo_obj:
            ativo_id = ativo_obj.id

    await movimento_repo.criar_movimento(
        session,
        tipo="saida",
        valor=fatura.valor_total,
        data=fatura.data_limite_pagamento,
        origem="documento",
        descricao=fatura.fornecedor_nome,
        documento_id=documento.id,
        fornecedor_id=fornecedor_id,
        titular_id=documento.registado_por,
        registado_por=documento.registado_por,
        ambito=documento.ambito,
        linhas=[
            movimento_repo.LinhaNova(
                valor=fatura.valor_total,
                categoria_id=categoria_id,
                # O consumo passa a viver na linha. A proteção contra ingestão dupla, que antes
                # vinha da constraint única de leitura_consumo, é agora dada pela idempotência ao
                # nível do documento (obter_por_paperless_id + o guard estado_validacao=="validado").
                quantidade=fatura.consumo.quantidade if fatura.consumo is not None else None,
                unidade=fatura.consumo.unidade if fatura.consumo is not None else None,
                ativo_id=ativo_id,
            )
        ],
    )

    documento.estado_validacao = "validado"


async def _processar_fatura_extraida(
    session: AsyncSession, *, documento: Documento, fatura: FaturaExtraida, referencia: date
) -> bool:
    fornecedor = await fornecedor_repo.obter_ou_criar(
        session, nome=fatura.fornecedor_nome, tipo=_inferir_tipo_fornecedor(fatura)
    )

    try:
        await validar_fatura(session, fatura, fornecedor_id=fornecedor.id, referencia=referencia)
    except FalhaValidacao:
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return False

    await _persistir_fatura(
        session,
        documento=documento,
        fatura=fatura,
        fornecedor_id=fornecedor.id,
        tipo_fornecedor=fornecedor.tipo,
    )
    await session.commit()
    return True


async def processar_documentos_pendentes(
    session: AsyncSession, paperless: PaperlessClient, *, referencia: date
) -> None:
    # A parte "tag -> lista de documentos -> salta já criados -> OCR + atribuição por tags" é
    # idêntica à de extratos.processar_extratos_pendentes e vive em
    # _comum._iterar_documentos_pendentes; o que diverge (nível-0 usa vários parsers em
    # cascata aqui vs. um só em extratos, ambito é usado aqui mas não lá, e faturas não tem o
    # branch "sem titular" nem o passo de reconciliação que extratos tem) fica em cada função.
    async for paperless_id, texto_ocr, registado_por, ambito, tag_id in _iterar_documentos_pendentes(
        session, paperless, TAG_POR_ESTRUTURAR
    ):
        fatura_nivel0 = None
        for parser in PARSERS_NIVEL0:
            fatura_nivel0 = parser(texto_ocr)
            if fatura_nivel0 is not None:
                break

        if fatura_nivel0 is not None:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=0,
                dados_extraidos=fatura_nivel0.model_dump(mode="json"),
                registado_por=registado_por,
                ambito=ambito,
            )
            validado = await _processar_fatura_extraida(
                session, documento=documento, fatura=fatura_nivel0, referencia=referencia
            )
            if validado:
                await paperless.remover_tag(paperless_id, tag_id=tag_id)
        else:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=1,
                dados_extraidos={},
                registado_por=registado_por,
                ambito=ambito,
            )
            await fila_repo.criar_item(session, documento_id=documento.id, texto_ocr=texto_ocr)
            await session.commit()


async def finalizar_documento_nivel1(
    session: AsyncSession, *, item_id: uuid.UUID, paperless: PaperlessClient, referencia: date
) -> None:
    # cabeçalho (fetch do item concluído + resolução/orfandade do documento) partilhado com
    # finalizar_extrato_nivel1 — ver _comum._obter_item_concluido_com_documento.
    resultado = await _obter_item_concluido_com_documento(session, item_id)
    if resultado is None:
        return
    item, documento = resultado

    if documento.estado_validacao == "validado":
        return  # já finalizado noutra corrida — idempotência (A2)

    try:
        fatura = FaturaExtraida.model_validate(item.resultado_json)
    except ValidationError:
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return

    documento.dados_extraidos = fatura.model_dump(mode="json")

    validado = await _processar_fatura_extraida(
        session, documento=documento, fatura=fatura, referencia=referencia
    )
    if validado:
        tag_id = await paperless.obter_id_de_tag(TAG_POR_ESTRUTURAR)
        await paperless.remover_tag(documento.paperless_document_id, tag_id=tag_id)
