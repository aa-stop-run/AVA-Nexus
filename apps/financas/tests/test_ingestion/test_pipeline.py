from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ava.extraction.schema import Consumo, FaturaExtraida
from ava.ingestion.pipeline import _persistir_fatura, finalizar_documento_nivel1, processar_documentos_pendentes
from ava.models.fornecedor import Fornecedor
from ava.models.grupo_categoria import GrupoCategoria
from ava.repositories import categoria_repo, documento_repo, fila_repo, fornecedor_repo


def _texto_fatura_edp() -> str:
        # cobertura dedicada ao parser). Reaproveitada aqui para provar o pipeline ponta-a-ponta:
    # valor_total=83,39€, data_limite_pagamento=2026-08-07, consumo=343 kWh.
    caminho = Path(__file__).parent.parent / "test_extraction" / "fixtures" / "fatura_edp.txt"
    return caminho.read_text(encoding="utf-8")


TEXTO_EDP = _texto_fatura_edp()


class FakePaperless:
    def __init__(
        self,
        documentos: dict[int, str],
        *,
        tags_por_documento: dict[int, list[int]] | None = None,
        mapa_tags: dict[int, str] | None = None,
    ):
        self._documentos = documentos
        self._tags_por_documento = tags_por_documento or {}
        self._mapa_tags = mapa_tags or {}
        self.tags_removidas: list[int] = []

    async def listar_documentos_por_tag(self, tag: str) -> list[dict]:
        return [
            {"id": doc_id, "tags": self._tags_por_documento.get(doc_id, [])} for doc_id in self._documentos
        ]

    async def obter_conteudo(self, document_id: int) -> str:
        return self._documentos[document_id]

    async def obter_id_de_tag(self, nome: str) -> int:
        return 99

    async def obter_mapa_de_tags(self) -> dict[int, str]:
        return self._mapa_tags

    async def remover_tag(self, document_id: int, tag_id: int) -> None:
        self.tags_removidas.append(document_id)


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_nivel0_persiste_despesa_e_consumo(db_session):
    from ava.repositories import movimento_repo

    paperless = FakePaperless({1: TEXTO_EDP})

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 1)
    assert documento is not None
    assert documento.nivel_extracao == 0
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [1]

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("83.39")

    # prova ponta-a-ponta de que a categorização automática depende da extração de consumo
    # (_inferir_tipo_fornecedor só classifica como "eletricidade" quando consumo.unidade ==
    # "kWh" — ver ava.ingestion.pipeline.faturas): sem o parser popular Consumo a partir da
    # tabela "Consumo real" real, este fornecedor cairia em "outro"/"Não classificado".
    fornecedor = await db_session.get(Fornecedor, movimentos[0].fornecedor_id)
    assert fornecedor is not None
    assert fornecedor.tipo == "eletricidade"


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_texto_desconhecido_vai_para_fila(db_session):
    paperless = FakePaperless({2: "um documento qualquer sem os campos esperados"})

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 2)
    assert documento is not None
    assert documento.nivel_extracao == 1
    assert paperless.tags_removidas == []  # ainda por processar — fica na fila para o worker


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_e_idempotente(db_session):
    from ava.repositories import movimento_repo

    paperless = FakePaperless({1: TEXTO_EDP})

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))
    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1  # não duplicou (A2)


@pytest.mark.asyncio
async def test_finalizar_documento_nivel1_persiste_apos_worker_responder(db_session):
    from ava.repositories import movimento_repo

    paperless = FakePaperless({3: "texto qualquer que o nível 0 não reconhece"})
    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 3)
    item = await fila_repo.obter_proximo_pendente(db_session)
    assert item is not None

    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "fornecedor_nome": "MEO",
            "nif_emissor": None,
            "iban": None,
            "valor_total": "29.99",
            "data_limite_pagamento": "2026-08-01",
            "linhas": [],
            "consumo": None,
        },
    )
    await db_session.commit()

    await finalizar_documento_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 27)
    )

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"
    assert paperless.tags_removidas == [3]

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("29.99")


@pytest.mark.asyncio
async def test_finalizar_documento_nivel1_e_idempotente_em_chamadas_repetidas(db_session):
    # regression test for the Critical finding: a retried /resultado POST (e.g. worker retry
    # after a network timeout) must not create a duplicate movimento for the same documento.
    from ava.repositories import movimento_repo

    paperless = FakePaperless({5: "texto qualquer que o nível 0 não reconhece"})
    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 5)
    item = await fila_repo.obter_proximo_pendente(db_session)
    assert item is not None

    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "fornecedor_nome": "MEO",
            "nif_emissor": None,
            "iban": None,
            "valor_total": "29.99",
            "data_limite_pagamento": "2026-08-01",
            "linhas": [],
            "consumo": None,
        },
    )
    await db_session.commit()

    await finalizar_documento_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 27)
    )
    # segunda chamada com o mesmo item_id — simula um retry do worker
    await finalizar_documento_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 27)
    )

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1  # não duplicou (A2)
    assert movimentos[0].valor == Decimal("29.99")


# test_extraction/test_parser_edp.py) com um NIF que falha o checksum de
# validadores.nif_valido — usado para exercitar o ramo de §7.1 em que o parser nível-0
# reconhece o documento mas a validação do pipeline rejeita o resultado.
TEXTO_EDP_NIF_INVALIDO = """
EDP Comercial - Comercialização de Energia, S.A.

Quanto tenho
a pagar?
45,67 €
Débito na minha
conta a partir de:
15 jul 2026

Os dados do meu contrato
NIF
196694532
"""


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_nivel0_falha_validacao_mantem_tag_e_marca_revisao_manual(
    db_session,
):
    # supplementary test (not in the brief's verbatim list): the brief's given tests never
    # exercise the branch where a nível-0 parser succeeds but §7.1 validation rejects the
    # result (here: a well-formed-looking but checksum-invalid NIF). This pins down the gate
    # that is the whole point of this task — persistence must not happen, and the paperless
    # tag must stay in place so the document surfaces for manual review.
    from ava.repositories import movimento_repo

    paperless = FakePaperless({4: TEXTO_EDP_NIF_INVALIDO})

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 4)
    assert documento is not None
    assert documento.nivel_extracao == 0
    assert documento.estado_validacao == "revisao_manual"
    assert paperless.tags_removidas == []  # falhou validação — tag fica para revisão manual

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert movimentos == []  # nada persistido enquanto a fatura não for aprovada


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_atribui_registado_por_e_ambito_via_tags(db_session):
    from ava.repositories import movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {1: TEXTO_EDP},
        tags_por_documento={1: [10, 11]},
        mapa_tags={10: f"telegram-titular-{titular.id}", 11: "ambito-pessoal"},
    )

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert movimentos[0].registado_por == titular.id
    assert movimentos[0].ambito == "pessoal"


@pytest.mark.asyncio
async def test_fatura_de_eletricidade_cria_movimento_com_contador_na_linha(db_session):
    from ava.financas.categorias_iniciais import semear_categorias
    from ava.repositories import movimento_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=901, nivel_extracao=0, dados_extraidos={}
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="EDP",
        valor_total=Decimal("95.40"),
        data_limite_pagamento=date(2026, 7, 26),
        consumo=Consumo(
            quantidade=Decimal("312"),
            unidade="kWh",
            periodo_inicio=date(2026, 6, 25),
            periodo_fim=date(2026, 7, 24),
        ),
    )
    await _persistir_fatura(
        db_session,
        documento=documento,
        fatura=fatura,
        fornecedor_id=fornecedor.id,
        tipo_fornecedor="eletricidade",
    )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    movimento = movimentos[0]
    assert movimento.tipo == "saida"
    assert movimento.valor == Decimal("95.40")
    assert movimento.origem == "documento"

    assert len(movimento.linhas) == 1
    linha = movimento.linhas[0]
    assert linha.quantidade == Decimal("312.000")
    assert linha.unidade == "kWh"

    categoria = await categoria_repo.obter_por_id(db_session, linha.categoria_id)
    assert categoria.nome == "Eletricidade"
    assert documento.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_fatura_nao_duplica_um_pagamento_ja_registado_pelo_banco(db_session):
    # Achado de 2026-08-20, direção inversa da correlação: quando o extrato/ficheiro do banco JÁ
    # tinha registado o pagamento antes de a fatura ser processada, _persistir_fatura criava um
    # segundo movimento (origem "documento") para o mesmo pagamento real -- nada verificava se o
        from ava.repositories import conta_repo, movimento_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    ja_registado = await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("83.39"), data=date(2026, 8, 7), origem="ficheiro",
        descricao="DD EDP COMERCIAL", conta_id=conta.id, titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("83.39"))],
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=902, nivel_extracao=0, dados_extraidos={},
        registado_por=titular.id,
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="EDP", valor_total=Decimal("83.39"), data_limite_pagamento=date(2026, 8, 7),
    )
    await _persistir_fatura(
        db_session, documento=documento, fatura=fatura, fornecedor_id=fornecedor.id,
        tipo_fornecedor="eletricidade",
    )
    await db_session.commit()
    await db_session.refresh(ja_registado)

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1
    assert ja_registado.fornecedor_id == fornecedor.id
    assert ja_registado.documento_id == documento.id
    assert documento.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_fatura_nao_confunde_pagamentos_de_titulares_diferentes(db_session):
    # Contraste do teste anterior: numa casa com dois titulares, um pagamento coincidente em
    # valor/data mas do OUTRO titular não pode ser confundido com esta fatura -- criaria uma
    # ligação fornecedor/documento errada e apagaria o alerta de "nunca foi debitada" para uma
    # fatura que pode continuar genuinamente por pagar.
    from ava.repositories import conta_repo, movimento_repo, titular_repo

    dono_do_banco = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    dono_da_fatura = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=dono_do_banco.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await movimento_repo.criar_movimento(
        db_session, tipo="saida", valor=Decimal("83.39"), data=date(2026, 8, 7), origem="ficheiro",
        descricao="Coincidência", conta_id=conta.id, titular_id=dono_do_banco.id,
        linhas=[movimento_repo.LinhaNova(valor=Decimal("83.39"))],
    )
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=903, nivel_extracao=0, dados_extraidos={},
        registado_por=dono_da_fatura.id,
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="EDP", valor_total=Decimal("83.39"), data_limite_pagamento=date(2026, 8, 7),
    )
    await _persistir_fatura(
        db_session, documento=documento, fatura=fatura, fornecedor_id=fornecedor.id,
        tipo_fornecedor="eletricidade",
    )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 2
    documento_movs = [m for m in movimentos if m.origem == "documento"]
    assert len(documento_movs) == 1
    assert documento_movs[0].fornecedor_id == fornecedor.id


@pytest.mark.asyncio
async def test_fatura_de_agua_cria_movimento_com_categoria_agua_e_unidade_m3(db_session):
    # Achado de revisão da Tarefa 4: só o ramo "eletricidade" de _CATEGORIA_POR_TIPO_FORNECEDOR
    # era verificado ponta-a-ponta contra as categorias semeadas. Este teste cobre o ramo "agua"
    # ("Habitação", "Água") — sem ele, um nome de grupo/categoria errado no mapa faria
    # obter_por_nomes devolver None e a linha ficaria silenciosamente sem categoria.
    from ava.financas.categorias_iniciais import semear_categorias
    from ava.repositories import movimento_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=902, nivel_extracao=0, dados_extraidos={}
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EPAL", tipo="agua")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="EPAL",
        valor_total=Decimal("32.10"),
        data_limite_pagamento=date(2026, 7, 26),
        consumo=Consumo(
            quantidade=Decimal("12"),
            unidade="m3",
            periodo_inicio=date(2026, 6, 25),
            periodo_fim=date(2026, 7, 24),
        ),
    )
    await _persistir_fatura(
        db_session,
        documento=documento,
        fatura=fatura,
        fornecedor_id=fornecedor.id,
        tipo_fornecedor="agua",
    )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    movimento = movimentos[0]
    assert movimento.tipo == "saida"
    assert movimento.valor == Decimal("32.10")

    assert len(movimento.linhas) == 1
    linha = movimento.linhas[0]
    assert linha.quantidade == Decimal("12.000")
    assert linha.unidade == "m3"  # valor guardado na BD, não "m³"

    categoria = await categoria_repo.obter_por_id(db_session, linha.categoria_id)
    assert categoria.nome == "Água"
    grupo = await db_session.get(GrupoCategoria, categoria.grupo_id)
    assert grupo.nome == "Habitação"
    assert documento.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_fatura_outro_cria_movimento_com_categoria_nao_classificado_e_sem_consumo(db_session):
    # Cobre o ramo "outro" ("Outros", "Não classificado") de _CATEGORIA_POR_TIPO_FORNECEDOR —
    # também o mesmo ramo pelo qual o fallback (ver teste seguinte) passa.
    from ava.financas.categorias_iniciais import semear_categorias
    from ava.repositories import movimento_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=903, nivel_extracao=0, dados_extraidos={}
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="MEO", tipo="outro")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="MEO",
        valor_total=Decimal("29.99"),
        data_limite_pagamento=date(2026, 7, 26),
        consumo=None,
    )
    await _persistir_fatura(
        db_session,
        documento=documento,
        fatura=fatura,
        fornecedor_id=fornecedor.id,
        tipo_fornecedor="outro",
    )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    movimento = movimentos[0]
    assert movimento.tipo == "saida"
    assert movimento.valor == Decimal("29.99")

    assert len(movimento.linhas) == 1
    linha = movimento.linhas[0]
    assert linha.quantidade is None
    assert linha.unidade is None

    categoria = await categoria_repo.obter_por_id(db_session, linha.categoria_id)
    assert categoria.nome == "Não classificado"
    grupo = await db_session.get(GrupoCategoria, categoria.grupo_id)
    assert grupo.nome == "Outros"
    assert documento.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_fatura_tipo_fornecedor_desconhecido_cai_no_mesmo_destino_que_outro(db_session):
    # Prova o fallback de _resolver_categoria_da_fatura: um tipo_fornecedor fora do mapa (aqui
    # "gas", que _inferir_tipo_fornecedor nunca produz, mas que podia chegar via
    # fornecedor.tipo já gravado por outro caminho) tem de resolver para a mesma categoria que
    # "outro" — ("Outros", "Não classificado") — via
    # `.get(..., _CATEGORIA_POR_TIPO_FORNECEDOR["outro"])`. Sem este teste, uma alteração futura
    # ao mapa podia trocar esse comportamento sem ninguém notar.
    from ava.financas.categorias_iniciais import semear_categorias
    from ava.repositories import movimento_repo

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=904, nivel_extracao=0, dados_extraidos={}
    )
    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="Fornecedor Gás Lda", tipo="gas")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="Fornecedor Gás Lda",
        valor_total=Decimal("18.50"),
        data_limite_pagamento=date(2026, 7, 26),
        consumo=None,
    )
    await _persistir_fatura(
        db_session,
        documento=documento,
        fatura=fatura,
        fornecedor_id=fornecedor.id,
        tipo_fornecedor="gas",
    )
    await db_session.commit()

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)
    )
    assert len(movimentos) == 1
    linha = movimentos[0].linhas[0]

    categoria = await categoria_repo.obter_por_id(db_session, linha.categoria_id)
    assert categoria.nome == "Não classificado"
    grupo = await db_session.get(GrupoCategoria, categoria.grupo_id)
    assert grupo.nome == "Outros"


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_persiste_e_marca_parser_nivel0(db_session):
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import fornecedor_repo, movimento_repo

    dados_fatura = {
        "fornecedor_nome": "Fornecedor Novo, Lda",
        "nif_emissor": None,
        "iban": None,
        "valor_total": "120.00",
        "data_limite_pagamento": "2026-08-01",
        "linhas": [],
        "consumo": None,
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=6,
        nivel_extracao=1,
        dados_extraidos=dados_fatura,
        estado_validacao="revisao_manual",
    )
    await db_session.commit()

    paperless = FakePaperless({})  # sem documentos pendentes — só usado para obter_id_de_tag/remover_tag

    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=paperless)

    assert aprovado is True
    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"
    assert paperless.tags_removidas == [6]

    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="Fornecedor Novo, Lda", tipo="outro")
    assert fornecedor.tem_parser_nivel0 is True

    movimentos = await movimento_repo.listar_por_periodo(
        db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31)
    )
    assert len(movimentos) == 1
    assert movimentos[0].valor == Decimal("120.00")


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_devolve_false_se_nao_estiver_em_revisao(db_session):
    from ava.ingestion.pipeline import aprovar_documento_manualmente

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=7, nivel_extracao=0, dados_extraidos={}, estado_validacao="validado"
    )
    await db_session.commit()

    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=FakePaperless({}))

    assert aprovado is False


TEXTO_EXTRATO = """
Banco: CGD
Conta: Conta à Ordem
Saldo inicial: -104,33 EUR
Saldo em 31/07/2026: 1350,00 EUR
Movimentos:
01/07/2026 | -45,67 | DD EDP COMERCIAL
15/07/2026 | 1500,00 | ORDENADO EMPRESA XPTO
"""
# checksum (Task 8): saldo_final - saldo_inicial = 1350.00 - (-104.33) = 1454.33 == -45.67 + 1500.00


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_nivel0_persiste_saldo_e_movimentos(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, linha_extrato_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {20: TEXTO_EXTRATO},
        tags_por_documento={20: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 20)
    assert documento is not None
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [20]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    assert contas[0].instituicao == "CGD"

    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, contas[0].id)
    assert saldo.valor == Decimal("1350.00")

    # a reconciliação corre logo a seguir à ingestão (Task 23): sem transações/rendimentos
    # correspondentes na BD, os 2 movimentos ficam em revisão manual, não pendentes.
    pendentes = await linha_extrato_repo.listar_pendentes(db_session)
    assert pendentes == []
    em_revisao = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert len(em_revisao) == 2


@pytest.mark.asyncio
async def test_extrato_substitui_ancora_de_ficheiro_na_mesma_data(db_session):
    # Achado 2 da revisão final da spec 2026-08-09: o ficheiro grava a âncora na `Data Mov.` do
    # lançamento mais recente e o extrato grava na data de fim do período — importar o ficheiro
    # nos primeiros dias do mês para ver a cauda do mês anterior (o caso de uso da própria spec)
    # faz as duas coincidirem. Antes desta correção, `except SaldoDuplicado: pass` engolia a
    # colisão em silêncio e a âncora do banco, a fonte de verdade, nunca chegava a gravar-se.
    from ava.extraction.schema_extrato import ExtratoBancario, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("-700.00"), origem="ficheiro",
    )
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=980, nivel_extracao=0, dados_extraidos={}
    )
    extrato = ExtratoBancario(
        instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
        saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-758.13")),
        saldo_inicial=Decimal("-758.13"),
        movimentos=[],
    )

    await _persistir_extrato(
        db_session, documento=documento, extrato=extrato, movimentos=[], titular_id=titular.id,
    )
    await db_session.commit()

    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert ancora.data == date(2026, 8, 3)
    assert ancora.valor == Decimal("-758.13")
    assert ancora.origem == "extrato"


@pytest.mark.asyncio
async def test_extrato_nao_toca_numa_ancora_de_extrato_ja_existente(db_session):
    # Contraste com o teste acima: a idempotência antiga (SaldoDuplicado -> pass) tem de se
    # manter intacta quando a âncora existente JÁ é de extrato — não pode ser tocada, nem quando
    # o valor deste novo extrato é diferente (ex. um reprocessamento com dados obsoletos).
    from ava.extraction.schema_extrato import ExtratoBancario, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await saldo_historico_repo.registar_saldo(
        db_session, conta_id=conta.id, data=date(2026, 8, 3), valor=Decimal("-500.00"), origem="extrato",
    )
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=981, nivel_extracao=0, dados_extraidos={}
    )
    extrato = ExtratoBancario(
        instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
        saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-999.99")),
        saldo_inicial=Decimal("-999.99"),
        movimentos=[],
    )

    await _persistir_extrato(
        db_session, documento=documento, extrato=extrato, movimentos=[], titular_id=titular.id,
    )
    await db_session.commit()

    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert ancora.valor == Decimal("-500.00")
    assert ancora.origem == "extrato"


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_sem_tag_de_titular_fica_em_revisao(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo

    paperless = FakePaperless({21: TEXTO_EXTRATO})  # sem tags_por_documento — sem atribuição de titular

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 21)
    assert documento.estado_validacao == "revisao_manual"
    # Fix 6: a tag É removida mesmo sem titular — caso contrário o documento reaparece sempre
    # nesta listagem do paperless (uma bandeira desatualizada, já que o documento já foi
    # triado para revisão manual), embora fique skippado pela idempotência de qualquer forma.
    assert paperless.tags_removidas == [21]

    # Fix 4: cair em revisão manual gera sempre um alerta ativo (A-P6), não só um estado passivo.
    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "documento_revisao_manual"
    assert alertas[0].chave_deduplicacao == f"documento_revisao_manual:{documento.id}"


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_texto_desconhecido_vai_para_fila(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {22: "um extrato qualquer sem os campos esperados"},
        tags_por_documento={22: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 22)
    assert documento.nivel_extracao == 1

    item = await fila_repo.obter_proximo_pendente(db_session)
    assert item is not None
    assert item.tipo == "extrato_bancario"


@pytest.mark.asyncio
async def test_finalizar_extrato_nivel1_persiste_apos_worker_responder(db_session):
    from ava.ingestion.pipeline import finalizar_extrato_nivel1, processar_extratos_pendentes
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {23: "texto de extrato não reconhecido"},
        tags_por_documento={23: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    item = await fila_repo.obter_proximo_pendente(db_session)
    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "instituicao": "CGD",
            "tipo_conta": "a_ordem",
            "nome_conta": "Conta à Ordem",
            "saldo_final": {"data": "2026-07-31", "valor": "1350.00"},
            # checksum (Task 8): 1350.00 - 1395.67 == -45.67
            "saldo_inicial": "1395.67",
            "movimentos": [{"data": "2026-07-01", "valor": "-45.67", "descricao": "DD EDP"}],
        },
    )
    await db_session.commit()

    await finalizar_extrato_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 31)
    )

    documento = await documento_repo.obter_por_id(db_session, item.documento_id)
    assert documento.estado_validacao == "validado"

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1


@pytest.mark.asyncio
async def test_finalizar_extrato_nivel1_e_idempotente_em_chamadas_repetidas(db_session):
    # regression-style test mirroring test_finalizar_documento_nivel1_e_idempotente_em_chamadas_repetidas:
    # linha_extrato has no unique constraint (unlike saldo_historico), so without the
    # documento.estado_validacao == "validado" guard, a retried /resultado POST would duplicate
    # the linha_extrato rows for the same extrato.
    from ava.ingestion.pipeline import finalizar_extrato_nivel1, processar_extratos_pendentes
    from ava.repositories import linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {26: "texto de extrato não reconhecido"},
        tags_por_documento={26: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    item = await fila_repo.obter_proximo_pendente(db_session)
    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "instituicao": "CGD",
            "tipo_conta": "a_ordem",
            "nome_conta": "Conta à Ordem",
            "saldo_final": {"data": "2026-07-31", "valor": "1350.00"},
            # checksum (Task 8): 1350.00 - 1395.67 == -45.67
            "saldo_inicial": "1395.67",
            "movimentos": [{"data": "2026-07-01", "valor": "-45.67", "descricao": "DD EDP"}],
        },
    )
    await db_session.commit()

    await finalizar_extrato_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 31)
    )
    # segunda chamada com o mesmo item_id — simula um retry do worker
    await finalizar_extrato_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 31)
    )

    # a reconciliação corre logo a seguir (Task 23): sem transação correspondente, o único
    # movimento fica em revisão manual, não pendente — o que importa aqui é que continua a
    # existir exatamente um, ou seja, a segunda chamada não duplicou (A2).
    pendentes = await linha_extrato_repo.listar_pendentes(db_session)
    assert pendentes == []
    em_revisao = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert len(em_revisao) == 1  # não duplicou (A2)


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_descarta_apenas_movimento_com_data_implausivel(db_session):
    # Fix 7 (regressão do finding original: "rejeita_movimento_com_data_implausivel"): um único
    # movimento com data implausível já não derruba o extrato inteiro — só esse movimento é
    # descartado, e o resto (saldo + outro movimento) continua a ser processado normalmente.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    # checksum (Task 8) sobre os movimentos TAL COMO LIDOS (antes do filtro de data implausível
    # que este teste exercita): 1350.00 - 1295.67 == -45.67 + 100.00
    texto_com_um_movimento_implausivel = """
    Banco: CGD
    Conta: Conta à Ordem
    Saldo inicial: 1295,67 EUR
    Saldo em 31/07/2026: 1350,00 EUR
    Movimentos:
    01/01/2028 | -45,67 | DD EDP COMERCIAL
    01/07/2026 | 100,00 | ORDENADO
    """
    paperless = FakePaperless(
        {24: texto_com_um_movimento_implausivel},
        tags_por_documento={24: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 24)
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [24]

    # só o movimento plausível (100,00) foi persistido; sem rendimento correspondente na BD,
    # fica em revisão manual de reconciliação (não descartado, não pendente).
    em_revisao = await linha_extrato_repo.listar_em_revisao_manual(db_session)
    assert len(em_revisao) == 1
    assert em_revisao[0].valor == Decimal("100.00")

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "linhas_extrato_ignoradas"
    assert alertas[0].chave_deduplicacao == f"linhas_extrato_ignoradas:{documento.id}"


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_rejeita_extrato_inteiro_quando_saldo_tem_data_implausivel(
    db_session,
):
    # ao contrário de um movimento individual (ver teste acima), uma data de saldo implausível
    # continua a derrubar o extrato inteiro para revisão manual — o saldo é a única secção
    # obrigatória e "tudo ou nada" de validar_extrato (Fix 7 não muda este comportamento).
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    texto_com_saldo_implausivel = """
    Banco: CGD
    Conta: Conta à Ordem
    Saldo em 31/12/2020: 1350,00 EUR
    Movimentos:
    01/07/2026 | -45,67 | DD EDP COMERCIAL
    """
    paperless = FakePaperless(
        {29: texto_com_saldo_implausivel},
        tags_por_documento={29: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 29)
    assert documento.estado_validacao == "revisao_manual"
    assert paperless.tags_removidas == []


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_sem_saldo_inicial_vai_para_revisao_manual_com_alerta(
    db_session,
):
    # Task 8 (A-P3, A-P6): um extrato bem formado (banco/conta/saldo final/movimentos todos
    # reconhecidos) mas sem "Saldo inicial" não é verificável — o checksum é impossível de
    # calcular, por isso FalhaValidacao cai no mesmo caminho de revisão manual + alerta ativo
    # que já existe para as outras falhas de validar_extrato (ver teste acima, saldo com data
    # implausível) — aqui provado especificamente end-to-end para o ramo "sem saldo inicial".
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    texto_sem_saldo_inicial = TEXTO_EXTRATO.replace("Saldo inicial: -104,33 EUR\n", "")
    paperless = FakePaperless(
        {28: texto_sem_saldo_inicial},
        tags_por_documento={28: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 28)
    assert documento.estado_validacao == "revisao_manual"
    assert paperless.tags_removidas == []  # falhou validação — tag fica para revisão manual

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "documento_revisao_manual"
    assert alertas[0].chave_deduplicacao == f"documento_revisao_manual:{documento.id}"


TEXTO_EXTRATO_COM_LINHA_NAO_RECONHECIDA = """
Banco: CGD
Conta: Conta à Ordem
Saldo inicial: 1395,67 EUR
Saldo em 31/07/2026: 1350,00 EUR
Movimentos:
01/07/2026 | -45,67 | DD EDP COMERCIAL
31/02/2026 | 100,00 | MOVIMENTO COM DATA INVALIDA
"""
# checksum (Task 8): a linha com data inválida (31/02) nem sequer entra em extrato.movimentos —
# é descartada já no parser (linhas_nao_reconhecidas), por isso o checksum só vê -45.67:
# 1350.00 - 1395.67 == -45.67


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_com_linhas_nao_reconhecidas_cria_alerta(db_session):
    # A-P6 (falha nunca é silenciosa): linhas_nao_reconhecidas > 0 no ExtratoBancario nível-0 tem
    # de gerar um alerta ativo, não só um log — ver banco_generico.py e schema_extrato.py.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {25: TEXTO_EXTRATO_COM_LINHA_NAO_RECONHECIDA},
        tags_por_documento={25: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 25)
    assert documento.estado_validacao == "validado"

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "linhas_extrato_ignoradas"
    assert alertas[0].chave_deduplicacao == f"linhas_extrato_ignoradas:{documento.id}"


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_sem_linhas_nao_reconhecidas_nao_cria_alerta(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {27: TEXTO_EXTRATO},  # extrato limpo — as duas linhas de movimento são reconhecidas
        tags_por_documento={27: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 31))

    documento = await documento_repo.obter_por_paperless_id(db_session, 27)
    assert documento.estado_validacao == "validado"

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert alertas == []


@pytest.mark.asyncio
async def test_finalizar_documento_nivel1_documento_inexistente_marca_erro(db_session):
    # item_fila aponta para um documento_id que não existe na BD — caso órfão, nunca deveria
    # acontecer, mas já não pode desaparecer num "return" silencioso (Fix 2).
    from ava.ingestion.pipeline import finalizar_documento_nivel1

    # criado sem documento_id (parâmetro opcional) — simula o item.documento_id apontar para
    # nada (órfão), o caso que o guard `if documento is None` protege.
    item = await fila_repo.criar_item(db_session, texto_ocr="texto qualquer")
    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "fornecedor_nome": "MEO",
            "nif_emissor": None,
            "iban": None,
            "valor_total": "29.99",
            "data_limite_pagamento": "2026-08-01",
            "linhas": [],
            "consumo": None,
        },
    )
    await db_session.commit()

    paperless = FakePaperless({})
    await finalizar_documento_nivel1(db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 27))

    item_atualizado = await fila_repo.obter_por_id(db_session, item.id)
    assert item_atualizado.estado == "erro"


@pytest.mark.asyncio
async def test_finalizar_documento_nivel1_falha_validacao_llm_marca_revisao_e_gera_alerta(db_session):
    # Fix 4: finalizar_documento_nivel1's except ValidationError já colocava o documento em
    # revisao_manual, mas sem alerta ativo — agora gera-se um.
    from ava.ingestion.pipeline import finalizar_documento_nivel1
    from ava.repositories import alerta_repo

    paperless = FakePaperless({8: "texto qualquer que o nível 0 não reconhece"})
    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 8)
    item = await fila_repo.obter_proximo_pendente(db_session)
    assert item is not None

    # resultado do worker não bate com o schema de FaturaExtraida (falta valor_total obrigatório)
    await fila_repo.concluir(db_session, item.id, {"fornecedor_nome": "MEO"})
    await db_session.commit()

    await finalizar_documento_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 27)
    )

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "revisao_manual"

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "documento_revisao_manual"
    assert alertas[0].chave_deduplicacao == f"documento_revisao_manual:{documento.id}"


@pytest.mark.asyncio
async def test_finalizar_extrato_nivel1_sem_titular_marca_erro(db_session):
    # Fix 2: o guard combinado "documento is None or documento.registado_por is None" cobria
    # dois casos bem diferentes com um único return mudo — agora cada um marca erro com uma
    # mensagem específica. Este teste cobre o caso "documento sem registado_por".
    from ava.ingestion.pipeline import finalizar_extrato_nivel1

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=30, nivel_extracao=1, dados_extraidos={}, registado_por=None
    )
    item = await fila_repo.criar_item(
        db_session, documento_id=documento.id, texto_ocr="extrato qualquer", tipo="extrato_bancario"
    )
    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "instituicao": "CGD",
            "tipo_conta": "a_ordem",
            "nome_conta": "Conta à Ordem",
            "saldo_final": {"data": "2026-07-31", "valor": "1350.00"},
            "movimentos": [],
        },
    )
    await db_session.commit()

    paperless = FakePaperless({})
    await finalizar_extrato_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 31)
    )

    item_atualizado = await fila_repo.obter_por_id(db_session, item.id)
    assert item_atualizado.estado == "erro"


@pytest.mark.asyncio
async def test_finalizar_extrato_nivel1_falha_validacao_llm_marca_revisao_e_gera_alerta(db_session):
    from ava.ingestion.pipeline import finalizar_extrato_nivel1
    from ava.repositories import alerta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=31, nivel_extracao=1, dados_extraidos={}, registado_por=titular.id
    )
    item = await fila_repo.criar_item(
        db_session, documento_id=documento.id, texto_ocr="extrato qualquer", tipo="extrato_bancario"
    )
    # resultado do worker não bate com o schema de ExtratoBancario (falta saldo_final obrigatório)
    await fila_repo.concluir(db_session, item.id, {"instituicao": "CGD"})
    await db_session.commit()

    paperless = FakePaperless({})
    await finalizar_extrato_nivel1(
        db_session, item_id=item.id, paperless=paperless, referencia=date(2026, 7, 31)
    )

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "revisao_manual"

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "documento_revisao_manual"
    assert alertas[0].chave_deduplicacao == f"documento_revisao_manual:{documento.id}"


# --- Fix 4: alerta ativo quando _processar_fatura_extraida cai em revisao_manual ---


@pytest.mark.asyncio
async def test_processar_documentos_pendentes_falha_validacao_gera_alerta_de_revisao_manual(db_session):
    from ava.repositories import alerta_repo

    paperless = FakePaperless({9: TEXTO_EDP_NIF_INVALIDO})

    await processar_documentos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 9)
    assert documento.estado_validacao == "revisao_manual"

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1
    assert alertas[0].tipo == "documento_revisao_manual"
    assert alertas[0].chave_deduplicacao == f"documento_revisao_manual:{documento.id}"


# --- Fix 6: aprovação manual de um extrato bancário em revisao_manual ---


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_aprova_extrato_bancario_em_revisao_manual(db_session):
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    dados_extrato = {
        "instituicao": "CGD",
        "tipo_conta": "a_ordem",
        "nome_conta": "Conta à Ordem",
        "saldo_final": {"data": "2020-12-31", "valor": "1350.00"},  # data implausível — daí a revisão
        "movimentos": [{"data": "2026-07-01", "valor": "-45.67", "descricao": "DD EDP"}],
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=32,
        nivel_extracao=0,
        dados_extraidos=dados_extrato,
        estado_validacao="revisao_manual",
        registado_por=titular.id,
    )
    await db_session.commit()

    paperless = FakePaperless({})

    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=paperless)

    assert aprovado is True
    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"
    # aprovação manual usa a tag de EXTRATO, não a de fatura (TAG_POR_ESTRUTURAR)
    assert paperless.tags_removidas == [32]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, contas[0].id)
    assert saldo.valor == Decimal("1350.00")


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_extrato_conta_unica_nao_funde_com_credito_existente(
    db_session,
):
    # Achado real (ingestão em produção): a aprovação manual de um extrato de CONTA ÚNICA
    # (BBVA/Cartão BPI Classic/Cartão Universo — ao contrário do caminho multi-conta do BPI
    # Integrado, que já tinha esta proteção desde a Tarefa 10) rebentava com
    # sqlalchemy.exc.MultipleResultsFound sempre que o titular já tivesse mais que uma conta
    # "divida" na mesma instituição — porque _aprovar_extrato_manualmente só passava
    # resolver_por_nome=True quando eh_multiconta, nunca para o formato de conta única.
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.flush()
    # Duas contas "divida" já existentes na MESMA instituição, nomes diferentes — reproduz
    # exatamente o cenário real (Crédito Pessoal + Cartão BPI Classic, ambas instituicao="BPI").
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Crédito Pessoal"
    )
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="divida", nome="Cartão BPI Classic 123"
    )
    await db_session.commit()

    dados_extrato = {
        "instituicao": "BPI",
        "tipo_conta": "divida",
        "nome_conta": "Cartão BPI Classic 123",
        "saldo_final": {"data": "2020-01-01", "valor": "500.00"},  # data implausível — daí a revisão
        "saldo_inicial": "480.00",
        "movimentos": [{"data": "2026-07-01", "valor": "20.00", "descricao": "Juros"}],
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=33,
        nivel_extracao=0,
        dados_extraidos=dados_extrato,
        estado_validacao="revisao_manual",
        registado_por=titular.id,
    )
    await db_session.commit()

    # A chamada em si não deve levantar MultipleResultsFound.
    aprovado = await aprovar_documento_manualmente(
        db_session, documento_id=documento.id, paperless=FakePaperless({})
    )

    assert aprovado is True
    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    # continuam a ser exatamente as 2 contas pré-existentes — nenhuma nova foi criada por engano,
    # e nenhuma das duas foi fundida com a outra (prova por comparação de id, não só contagem).
    assert len(contas) == 2
    conta_cartao = next(c for c in contas if c.nome == "Cartão BPI Classic 123")
    conta_pessoal = next(c for c in contas if c.nome == "Crédito Pessoal")
    assert conta_cartao.id != conta_pessoal.id


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_extrato_sem_titular_devolve_false(db_session):
    # sem titular associado não há como criar a `conta` — mesma limitação documentada em
    # _aprovar_extrato_manualmente.
    from ava.ingestion.pipeline import aprovar_documento_manualmente

    dados_extrato = {
        "instituicao": "CGD",
        "tipo_conta": "a_ordem",
        "nome_conta": "Conta à Ordem",
        "saldo_final": {"data": "2020-12-31", "valor": "1350.00"},
        "movimentos": [],
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=33,
        nivel_extracao=0,
        dados_extraidos=dados_extrato,
        estado_validacao="revisao_manual",
        registado_por=None,
    )
    await db_session.commit()

    aprovado = await aprovar_documento_manualmente(
        db_session, documento_id=documento.id, paperless=FakePaperless({})
    )

    assert aprovado is False


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_dados_vazios_devolve_false(db_session):
    # dados_extraidos == {} não bate em nenhum dos dois schemas — caso já conhecido (pré-existente
    # para faturas nível1) que continua fora do âmbito de resolução automática (ver Fix 6).
    from ava.ingestion.pipeline import aprovar_documento_manualmente

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=34, nivel_extracao=0, dados_extraidos={}, estado_validacao="revisao_manual"
    )
    await db_session.commit()

    aprovado = await aprovar_documento_manualmente(
        db_session, documento_id=documento.id, paperless=FakePaperless({})
    )

    assert aprovado is False


@pytest.mark.asyncio
async def test_validar_fatura_fora_da_magnitude_historica_do_ledger_levanta_falha_validacao(db_session):
    # Regressão da Tarefa 4: _persistir_fatura passou a escrever em movimento, mas validar_fatura
    # continuava a ler o histórico de transacao_repo — tabela que deixou de receber escritas do
    # caminho de faturas. O histórico ficava sempre vazio e valor_dentro_magnitude_historica
    # devolve True para lista vazia (nada para comparar ainda), tornando o teto um no-op
    # silencioso. Este teste cria o histórico através do ledger (movimento_repo.criar_movimento)
    # para provar que o teto volta a disparar — um teste que leia de transacao_repo não provaria
    # nada, porque passaria tanto com o defeito como sem ele.
    from ava.ingestion.pipeline import FalhaValidacao, validar_fatura
    from ava.repositories import movimento_repo

    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    # histórico: 3 saídas deste fornecedor à volta de 50€, criadas através do ledger novo
    for dia, valor in ((1, "48.00"), (2, "50.00"), (3, "52.00")):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal(valor),
            data=date(2026, 6, dia),
            origem="documento",
            fornecedor_id=fornecedor.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal(valor))],
        )
    await db_session.commit()

    # média histórica ~50€ -> teto = 50 * 3 = 150€; 500€ foge muito da banda
    fatura = FaturaExtraida(
        fornecedor_nome="EDP",
        valor_total=Decimal("500.00"),
        data_limite_pagamento=date(2026, 7, 15),
    )

    with pytest.raises(FalhaValidacao):
        await validar_fatura(db_session, fatura, fornecedor_id=fornecedor.id, referencia=date(2026, 7, 10))


@pytest.mark.asyncio
async def test_validar_fatura_dentro_da_magnitude_historica_do_ledger_nao_levanta(db_session):
    # Caso simétrico do teste acima: um valor dentro da banda [média/3, média*3] não deve ser
    # rejeitado quando o histórico vem do ledger.
    from ava.ingestion.pipeline import validar_fatura
    from ava.repositories import movimento_repo

    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="EDP", tipo="eletricidade")
    await db_session.commit()

    for dia, valor in ((1, "48.00"), (2, "50.00"), (3, "52.00")):
        await movimento_repo.criar_movimento(
            db_session,
            tipo="saida",
            valor=Decimal(valor),
            data=date(2026, 6, dia),
            origem="documento",
            fornecedor_id=fornecedor.id,
            linhas=[movimento_repo.LinhaNova(valor=Decimal(valor))],
        )
    await db_session.commit()

    # média histórica ~50€ -> banda [16.67€, 150€]; 55€ está dentro
    fatura = FaturaExtraida(
        fornecedor_nome="EDP",
        valor_total=Decimal("55.00"),
        data_limite_pagamento=date(2026, 7, 15),
    )

    await validar_fatura(db_session, fatura, fornecedor_id=fornecedor.id, referencia=date(2026, 7, 10))


@pytest.mark.asyncio
async def test_validar_fatura_valor_total_nao_positivo_levanta_falha_validacao(db_session):
    # Achado 3 (revisão final de fecho da Fase A): FaturaExtraida.valor_total não tem constraint de
    # schema (Decimal livre) — um valor <= 0 (dados extraídos incorretamente, p.ex.) só era apanhado
    # tarde de mais, dentro de _persistir_fatura via movimento_repo.criar_movimento
    # (ValorNaoPositivo), depois de validar_fatura já ter dado luz verde. No caminho automático
    # (nível-0/nível-1, via _processar_fatura_extraida) essa exceção subiria sem tratamento pelo
    # job_ingestao agendado, que não tem nenhum try/except geral — podendo bloquear a corrida
    # inteira. Mesmo mecanismo já usado para data implausível, NIF, IBAN e magnitude histórica:
    # FalhaValidacao encaminha para revisao_manual + alerta ativo em vez de rebentar.
    from ava.ingestion.pipeline import FalhaValidacao, validar_fatura

    fornecedor = await fornecedor_repo.obter_ou_criar(db_session, nome="Fornecedor Zero", tipo="outro")
    await db_session.commit()

    fatura = FaturaExtraida(
        fornecedor_nome="Fornecedor Zero",
        valor_total=Decimal("0"),
        data_limite_pagamento=date(2026, 7, 15),
    )

    with pytest.raises(FalhaValidacao):
        await validar_fatura(db_session, fatura, fornecedor_id=fornecedor.id, referencia=date(2026, 7, 10))


@pytest.mark.asyncio
async def test_aprovar_documento_manualmente_fatura_valor_zero_devolve_false_sem_rebentar(db_session):
    # Achado 3 (revisão final de fecho da Fase A): uma fatura de 0,00€ em revisao_manual (dados
    # extraídos incorretamente, p.ex.) não pode ficar presa para sempre — a única ação da UI é
    # "Aprovar" (rota POST /revisao/{id}/aprovar). A aprovação manual passa propositadamente ao
    # lado de validar_fatura (é o mecanismo de override do utilizador para faturas que caíram em
    # revisao_manual por outros motivos), por isso o crivo tem de vir de
    # movimento_repo.criar_movimento (ValorNaoPositivo) — antes desta correção essa exceção não era
    # apanhada em aprovacao.py e rebentava com 500. Devolve False de forma limpa: o documento
    # continua em revisao_manual, nenhum movimento é criado.
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import movimento_repo

    dados_fatura = {
        "fornecedor_nome": "Fornecedor Zero",
        "nif_emissor": None,
        "iban": None,
        "valor_total": "0.00",
        "data_limite_pagamento": "2026-08-01",
        "linhas": [],
        "consumo": None,
    }
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=501,
        nivel_extracao=1,
        dados_extraidos=dados_fatura,
        estado_validacao="revisao_manual",
    )
    await db_session.commit()
    # Capturado ANTES de invocar a função em teste: aprovar_documento_manualmente chama
    # session.rollback() no ramo ValorNaoPositivo, o que expira todos os objetos ORM da sessão —
    # ler documento.id depois disso rebentaria com MissingGreenlet (mesmo padrão já usado nos
    # testes de recorrentes/obrigações para o mesmo motivo).
    documento_id = documento.id

    aprovado = await aprovar_documento_manualmente(
        db_session, documento_id=documento_id, paperless=FakePaperless({})
    )

    assert aprovado is False
    documento_atualizado = await documento_repo.obter_por_id(db_session, documento_id)
    assert documento_atualizado.estado_validacao == "revisao_manual"
    assert (
        await movimento_repo.listar_por_periodo(db_session, inicio=date(2026, 8, 1), fim=date(2026, 8, 31))
        == []
    )


# --- Task 8: checksum de saldo_inicial/saldo_final em validar_extrato (A-P3, A-P6) ---
# Sem docker/db envolvidos — validar_extrato é síncrona e pura, testada diretamente contra
# ExtratoBancario construído em memória (mesmo padrão dos testes de validar_fatura acima).


def _extrato_teste(*, saldo_inicial, saldo_final_valor, movimentos_valores, saldo_final_data=None):
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal

    return ExtratoBancario(
        instituicao="CGD",
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem",
        saldo_final=SaldoFinal(
            data=saldo_final_data or date(2026, 7, 31), valor=Decimal(saldo_final_valor)
        ),
        saldo_inicial=Decimal(saldo_inicial) if saldo_inicial is not None else None,
        movimentos=[
            MovimentoExtraido(data=date(2026, 7, 15), valor=Decimal(valor), descricao=f"mov {i}")
            for i, valor in enumerate(movimentos_valores)
        ],
    )


def test_validar_extrato_aceita_quando_o_checksum_fecha():
    from ava.ingestion.pipeline import validar_extrato

    # saldo_inicial 1000, final 1100, movimentos +200 -100 -> fecha
    extrato = _extrato_teste(
        saldo_inicial="1000.00", saldo_final_valor="1100.00", movimentos_valores=["200.00", "-100.00"]
    )

    validos, ignorados = validar_extrato(extrato, referencia=date(2026, 7, 31))

    assert len(validos) == 2
    assert ignorados == 0


def test_validar_extrato_rejeita_quando_o_checksum_nao_fecha():
    from ava.ingestion.pipeline import FalhaValidacao, validar_extrato

    # saldo_inicial 1000, final 1100, mas movimentos somam +150 -> falta uma linha
    extrato = _extrato_teste(
        saldo_inicial="1000.00", saldo_final_valor="1100.00", movimentos_valores=["150.00"]
    )

    with pytest.raises(FalhaValidacao, match="checksum"):
        validar_extrato(extrato, referencia=date(2026, 7, 31))


def test_validar_extrato_rejeita_sem_saldo_inicial():
    from ava.ingestion.pipeline import FalhaValidacao, validar_extrato

    # o caminho nível-1 (LLM) pode não devolver saldo_inicial. Sem ele o checksum é impossível,
    # e um extrato não verificável não é de confiar (A-P3).
    extrato = _extrato_teste(
        saldo_inicial=None, saldo_final_valor="1100.00", movimentos_valores=["100.00"]
    )

    with pytest.raises(FalhaValidacao, match="saldo inicial"):
        validar_extrato(extrato, referencia=date(2026, 7, 31))


def test_validar_extrato_checksum_usa_movimentos_como_lidos_antes_do_filtro_de_data():
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline import validar_extrato

    # Ordem importa (ver nota em extratos.py::validar_extrato): o checksum tem de correr sobre os
    # movimentos tal como lidos, ANTES do filtro de data implausível (Fix 7). Se o filtro corresse
    # primeiro, este teste falharia com "checksum não fecha" assim que o movimento com data
    # implausível fosse removido — transformando uma degradação tolerada num erro.
    extrato = ExtratoBancario(
        instituicao="CGD",
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem",
        saldo_final=SaldoFinal(data=date(2026, 7, 31), valor=Decimal("1200.00")),
        saldo_inicial=Decimal("1000.00"),
        movimentos=[
            MovimentoExtraido(data=date(2028, 1, 1), valor=Decimal("250.00"), descricao="data implausível"),
            MovimentoExtraido(data=date(2026, 7, 15), valor=Decimal("-50.00"), descricao="plausível"),
        ],
    )

    # checksum: 1200.00 - 1000.00 = 200.00 == 250.00 + (-50.00) -- fecha só se somado ANTES do filtro
    validos, ignorados = validar_extrato(extrato, referencia=date(2026, 7, 31))

    assert len(validos) == 1
    assert validos[0].descricao == "plausível"
    assert ignorados == 1


# --- Tarefa 10: Extracto Integrado do BPI (multi-conta num só documento) ---
# Ao contrário de banco_generico.py (um produto financeiro por documento), o Extracto Integrado
# do BPI cobre até 5 produtos financeiros num só PDF. Este teste prova ponta-a-ponta que:
#   1. as 4 secções do fixture (a_ordem, poupança, crédito pessoal, crédito habitação) viram 4
#      Conta distintas, cada uma com o seu saldo_historico;
#   2. as duas contas de crédito (mesma instituicao="BPI", mesmo tipo="divida") NÃO se fundem —
#      a armadilha que obter_ou_criar_por_instituicao teria cometido (ver conta_repo.py).


def _texto_extrato_bpi() -> str:
    caminho = Path(__file__).parent.parent / "test_extraction" / "fixtures" / "extrato_bpi_integrado.txt"
    return caminho.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_bpi_cria_quatro_contas_distintas(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    paperless = FakePaperless(
        {40: _texto_extrato_bpi()},
        tags_por_documento={40: [60]},
        mapa_tags={60: f"telegram-titular-{titular.id}"},
    )

    # referencia = data de emissão/fim de período do fixture (03/07/2026) — dentro da margem de
    # plausibilidade tanto do saldo final (§ data_plausivel) como de todos os movimentos.
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 3))

    documento = await documento_repo.obter_por_paperless_id(db_session, 40)
    assert documento is not None
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [40]  # só remove a tag quando as 4 secções validam

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 4
    assert {c.instituicao for c in contas} == {"BPI"}
    assert {c.tipo for c in contas} == {"a_ordem", "poupanca", "divida"}
    nomes = {c.nome for c in contas}
    assert nomes == {
        "CONTA VALOR TESTE BPI Nº: 0000000-000-001",
        "BPI POUPANCA TESTE",
        "Crédito Pessoal",
        "Mortgage & Loans/Hipotecário",
    }

    # a armadilha central desta tarefa: as duas contas "divida" são objetos Conta DISTINTOS
    # (não só "não deu erro") — obter_ou_criar_por_instituicao (sem "nome" no critério de
    # combinação) tê-las-ia fundido numa só, por teren a mesma instituicao e o mesmo tipo.
    contas_divida = {c.nome: c for c in contas if c.tipo == "divida"}
    assert len(contas_divida) == 2
    conta_pessoal = contas_divida["Crédito Pessoal"]
    conta_habitacao = contas_divida["Mortgage & Loans/Hipotecário"]
    assert conta_pessoal.id != conta_habitacao.id
    assert conta_pessoal.categoria_divida is None  # âmbito de tarefa futura

    saldo_pessoal = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_pessoal.id)
    saldo_habitacao = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_habitacao.id)
    assert saldo_pessoal.valor == Decimal("5000.00")
    assert saldo_habitacao.valor == Decimal("60000.00")

    conta_a_ordem = next(c for c in contas if c.tipo == "a_ordem")
    conta_poupanca = next(c for c in contas if c.tipo == "poupanca")
    saldo_a_ordem = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_a_ordem.id)
    saldo_poupanca = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_poupanca.id)
    assert saldo_a_ordem.valor == Decimal("1240.90")
    assert saldo_poupanca.valor == Decimal("36.00")


# --- BBVA: crédito automóvel, conta de saldo único (sem lista de movimentos) ---
# Ao contrário do Extracto Integrado do BPI (5 secções) e mais simples até que o próprio
# banco_generico.py, o extrato do BBVA é uma só conta que só regista "Capital vincendo" (o saldo
# em dívida) — decisão de desenho: o documento não permite isolar com exatidão só a parte de
# capital do movimento "Recebimento prestação" (só o total vem, sem a divisão capital/juros/selo,
# que só é mostrada para a PRÓXIMA prestação). Este teste prova ponta-a-ponta que o checksum
# trivial (saldo_inicial = saldo_final, sem movimentos) fecha sozinho — o documento fica
# "validado", não "revisao_manual", sem qualquer intervenção manual.


def _texto_extrato_bbva() -> str:
    caminho = Path(__file__).parent.parent / "test_extraction" / "fixtures" / "extrato_bbva_credito.txt"
    return caminho.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_bbva_cria_conta_divida_com_saldo(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {70: _texto_extrato_bbva()},
        tags_por_documento={70: [80]},
        mapa_tags={80: f"telegram-titular-{titular.id}"},
    )

    # referencia = data de emissão do fixture (27/07/2026) — dentro da margem de plausibilidade
    # do saldo (não há movimentos para verificar plausibilidade de data).
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    documento = await documento_repo.obter_por_paperless_id(db_session, 70)
    assert documento is not None
    # A prova central: o checksum trivial (saldo_inicial == saldo_final, sem movimentos) fecha
    # sozinho — o documento NÃO cai em revisão manual só por não ter movimentos.
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [70]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    conta = contas[0]
    assert conta.instituicao == "BBVA"
    assert conta.tipo == "divida"
    assert "0000000" in conta.nome  # número do contrato — estável entre meses

    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert saldo.valor == Decimal("2500.00")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_bbva_dois_contratos_nao_se_fundem(db_session):
    # Achado do code-reviewer (revisão desta tarefa): instituicao="BBVA" e tipo_conta="divida"
    # são IGUAIS para qualquer contrato de crédito automóvel BBVA — só nome_conta varia (número
    # do contrato). Isto é exatamente a mesma armadilha já resolvida para as duas secções de
    # crédito do BPI (ver bloco abaixo, "Crédito Pessoal" vs "Mortgage & Loans/Hipotecário"):
    # sem resolver_por_nome=True, obter_ou_criar_por_instituicao (que combina só por
    # titular_id+instituicao+tipo, sem olhar para nome) fundiria dois contratos BBVA distintos do
    # mesmo titular numa só Conta, misturando o histórico de saldo de dois créditos diferentes.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    texto_contrato_1 = _texto_extrato_bbva()
    # Segundo contrato: mesmo layout de documento, só o número do contrato muda (simula um
    # segundo crédito automóvel BBVA do mesmo titular).
    texto_contrato_2 = texto_contrato_1.replace("Plate 0000000 /", "Plate 1111111 /")

    paperless = FakePaperless(
        {71: texto_contrato_1, 72: texto_contrato_2},
        tags_por_documento={71: [80], 72: [80]},
        mapa_tags={80: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 27))

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2  # a prova central: NÃO se fundiram numa só Conta
    nomes = {c.nome for c in contas}
    assert nomes == {
        "Crédito Automóvel BBVA — Contrato 0000000",
        "Crédito Automóvel BBVA — Contrato 1111111",
    }
    for conta in contas:
        assert conta.instituicao == "BBVA"
        assert conta.tipo == "divida"
        saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
        assert saldo.valor == Decimal("2500.00")


# --- Cartão de Crédito BPI Classic: conta única, checksum via RESUMO (sem derivação) ---
# Ao contrário das secções de crédito do Extracto Integrado (juros/imposto do selo EXCLUÍDOS dos
# o cartão de crédito inclui TODOS os movimentos que aumentam o saldo em dívida — compras,
# comissões, imposto do selo e juros — porque não há "conta à ordem paralela" onde já apareçam.
# saldo_inicial vem explícito no RESUMO (não é derivado), por isso o checksum de §7 é uma
# verificação real aqui, tal como na secção "Depósitos à Ordem" do BPI Integrado.


def _texto_extrato_cartao_bpi_classic_sem_pagamento() -> str:
    caminho = (
        Path(__file__).parent.parent
        / "test_extraction"
        / "fixtures"
        / "extrato_cartao_bpi_classic_sem_pagamento.txt"
    )
    return caminho.read_text(encoding="utf-8")


def _texto_extrato_cartao_bpi_classic_com_pagamento_e_juros() -> str:
    caminho = (
        Path(__file__).parent.parent
        / "test_extraction"
        / "fixtures"
        / "extrato_cartao_bpi_classic_com_pagamento_e_juros.txt"
    )
    return caminho.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_cartao_bpi_classic_cria_conta_divida_e_valida(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, linha_extrato_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {90: _texto_extrato_cartao_bpi_classic_sem_pagamento()},
        tags_por_documento={90: [100]},
        mapa_tags={100: f"telegram-titular-{titular.id}"},
    )

    # referencia = data de emissão do extracto actual do fixture (05/04/2026) — dentro da margem
    # de plausibilidade tanto do saldo final quanto dos movimentos (todos datados de 11/03/2026,
    # ~25 dias antes, bem dentro da margem de 90 dias).
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 4, 5))

    documento = await documento_repo.obter_por_paperless_id(db_session, 90)
    assert documento is not None
    # A prova central: o checksum via RESUMO (saldo explícito, sem derivação) fecha sozinho —
    # o documento fica "validado", não "revisao_manual".
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [90]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    conta = contas[0]
    assert conta.instituicao == "BPI"
    assert conta.tipo == "divida"
    assert conta.nome == "Cartão BPI Classic 00000000000000000000"

    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert saldo.valor == Decimal("523.92")

    # sem movimentos existentes para conciliar, reconciliar_linhas_pendentes marca as linhas como
    # "revisao_manual" (0 candidatos, ver reconciliacao.conciliar_uma_linha) — não há função
    # listar_por_conta em linha_extrato_repo, por isso filtra-se pelo conta_id aqui.
    linhas = [
        linha
        for linha in await linha_extrato_repo.listar_em_revisao_manual(db_session)
        if linha.conta_id == conta.id
    ]
    assert len(linhas) == 5
    assert sum((linha.valor for linha in linhas), Decimal("0")) == Decimal("523.92")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_cartao_bpi_classic_com_pagamento_e_juros_valida(db_session):
    # Mês com AMBAS as secções opcionais presentes (PAGAMENTOS e JUROS (MOVIMENTOS HABITUAIS)) —
    # prova que o parser lida com o documento "cheio", não só com o caso mínimo.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, linha_extrato_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {91: _texto_extrato_cartao_bpi_classic_com_pagamento_e_juros()},
        tags_por_documento={91: [101]},
        mapa_tags={101: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 5, 5))

    documento = await documento_repo.obter_por_paperless_id(db_session, 91)
    assert documento is not None
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [91]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, contas[0].id)
    assert saldo.valor == Decimal("339.98")

    linhas = [
        linha
        for linha in await linha_extrato_repo.listar_em_revisao_manual(db_session)
        if linha.conta_id == contas[0].id
    ]
    # PAGAMENTO AUTOMATICO + CASH ADVANCE + 6 linhas de comissões/imposto do selo + JUROS = 9.
    assert len(linhas) == 9
    assert sum((linha.valor for linha in linhas), Decimal("0")) == Decimal("-183.94")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_cartao_bpi_classic_dois_cartoes_nao_se_fundem(db_session):
    # Mesma armadilha já resolvida para BBVA (test_processar_extratos_pendentes_bbva_
    # dois_contratos_nao_se_fundem) e para as duas secções de crédito do BPI Integrado:
    # instituicao="BPI" e tipo_conta="divida" são IGUAIS para qualquer cartão de crédito BPI
        # resolver_por_nome=True, obter_ou_criar_por_instituicao fundiria dois cartões distintos do
    # mesmo titular numa só Conta, misturando o histórico de saldo de dois cartões diferentes.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    texto_cartao_1 = _texto_extrato_cartao_bpi_classic_sem_pagamento()
    # Segundo cartão: mesmo layout de documento, só o número da conta-cartão muda (simula um
    # segundo Cartão BPI Classic do mesmo titular).
    texto_cartao_2 = texto_cartao_1.replace(
        "Conta cartão nº 00000000000000000000", "Conta cartão nº 11111111111111111111"
    )
    assert "11111111111111111111" in texto_cartao_2

    paperless = FakePaperless(
        {92: texto_cartao_1, 93: texto_cartao_2},
        tags_por_documento={92: [100], 93: [100]},
        mapa_tags={100: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 4, 5))

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2  # a prova central: NÃO se fundiram numa só Conta
    nomes = {c.nome for c in contas}
    assert nomes == {
        "Cartão BPI Classic 00000000000000000000",
        "Cartão BPI Classic 11111111111111111111",
    }

    conta_a = next(c for c in contas if c.nome == "Cartão BPI Classic 00000000000000000000")
    conta_b = next(c for c in contas if c.nome == "Cartão BPI Classic 11111111111111111111")
    # comparação explícita (nota do último review sobre o teste equivalente do BBVA): não basta
    # "não deu erro" — os dois objetos Conta têm de ser DISTINTOS.
    assert conta_a.id != conta_b.id

    for conta in contas:
        assert conta.instituicao == "BPI"
        assert conta.tipo == "divida"
        saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
        assert saldo.valor == Decimal("523.92")


# --- Cartão Universo: conta única, checksum via RESUMO (sem derivação), movimentos com sinal
# invertido face à secção "EXTRATO MOVIMENTOS - CONTA CRÉDITO" ---
# Ao contrário do Cartão BPI Classic (mesma convenção de sinal em toda a secção de movimentos), o
# Cartão Universo tem uma secção de movimentos cuja convenção de sinal é OPOSTA à do RESUMO — ver


def _texto_extrato_cartao_universo() -> str:
    caminho = Path(__file__).parent.parent / "test_extraction" / "fixtures" / "extrato_cartao_universo.txt"
    return caminho.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_cartao_universo_cria_conta_divida_e_valida(db_session):
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, linha_extrato_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    paperless = FakePaperless(
        {110: _texto_extrato_cartao_universo()},
        tags_por_documento={110: [120]},
        mapa_tags={120: f"telegram-titular-{titular.id}"},
    )

    # referencia = data de emissão do extrato atual do fixture (15/07/2026) — dentro da margem de
    # plausibilidade tanto do saldo final quanto dos movimentos (todos entre 23/06 e 14/07/2026).
    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 15))

    documento = await documento_repo.obter_por_paperless_id(db_session, 110)
    assert documento is not None
    # A prova central: o checksum via RESUMO (saldo explícito, sem derivação) fecha sozinho, com
    # os movimentos de sinal invertido — o documento fica "validado", não "revisao_manual".
    assert documento.estado_validacao == "validado"
    assert paperless.tags_removidas == [110]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1
    conta = contas[0]
    assert conta.instituicao == "Universo"
    assert conta.tipo == "divida"
    assert conta.nome == "Cartão Universo 00000000000000"

    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert saldo.valor == Decimal("172.72")

    # sem movimentos existentes para conciliar, reconciliar_linhas_pendentes marca as linhas como
    # "revisao_manual" (0 candidatos, ver reconciliacao.conciliar_uma_linha).
    linhas = [
        linha
        for linha in await linha_extrato_repo.listar_em_revisao_manual(db_session)
        if linha.conta_id == conta.id
    ]
    assert len(linhas) == 5
    # -18,43 (pagamento) + 3,99 + 0,09 + 2,28 + 0,25 (encargos) = -11,82.
    assert sum((linha.valor for linha in linhas), Decimal("0")) == Decimal("-11.82")


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_cartao_universo_dois_contratos_nao_se_fundem(db_session):
    # Mesma armadilha já resolvida para BBVA e para o Cartão BPI Classic: instituicao="Universo"
    # e tipo_conta="divida" são IGUAIS para qualquer contrato Universo — só nome_conta varia
        # obter_ou_criar_por_instituicao fundiria dois contratos distintos do mesmo titular numa só
    # Conta, misturando o histórico de saldo de dois cartões diferentes.
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.commit()

    texto_contrato_1 = _texto_extrato_cartao_universo()
    # Segundo contrato: mesmo layout de documento, só o número do contrato muda (simula um
    # segundo Cartão Universo do mesmo titular).
    texto_contrato_2 = texto_contrato_1.replace(
        "Acessório Nº 00000000000000", "Acessório Nº 11111111111111"
    )
    assert "Acessório Nº 11111111111111" in texto_contrato_2

    paperless = FakePaperless(
        {111: texto_contrato_1, 112: texto_contrato_2},
        tags_por_documento={111: [120], 112: [120]},
        mapa_tags={120: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 15))

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2  # a prova central: NÃO se fundiram numa só Conta
    nomes = {c.nome for c in contas}
    assert nomes == {
        "Cartão Universo 00000000000000",
        "Cartão Universo 11111111111111",
    }

    conta_a = next(c for c in contas if c.nome == "Cartão Universo 00000000000000")
    conta_b = next(c for c in contas if c.nome == "Cartão Universo 11111111111111")
    # comparação explícita (padrão já estabelecido nos testes equivalentes de BBVA e Cartão BPI
    # Classic): não basta "não deu erro" — os dois objetos Conta têm de ser DISTINTOS.
    assert conta_a.id != conta_b.id

    for conta in contas:
        assert conta.instituicao == "Universo"
        assert conta.tipo == "divida"
        saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
        assert saldo.valor == Decimal("172.72")


# --- Achado Importante (revisão Tarefa 10): estado_validacao agregado no ciclo BPI, e
# _aprovar_extrato_manualmente capaz do formato multi-conta ---
#
# Antes da correção, cada chamada a _processar_extrato_extraido escrevia
# documento.estado_validacao incondicionalmente ("validado" ou "revisao_manual") contra o MESMO
# `Documento`, e como as chamadas são sequenciais sobre o mesmo objeto, a ÚLTIMA secção
# processada decidia sozinha o estado final — mesmo que uma secção anterior tivesse falhado
# (e nunca persistido linha_extrato/saldo_historico). Separadamente, _aprovar_extrato_manualmente
# só sabia validar contra um ExtratoBancario único; para o caminho BPI (dados_extraidos com a
# forma {"contas": [...]}) isso levantava ValidationError sempre, devolvendo False em silêncio —
# nenhuma via de recuperação manual para um extracto integrado em revisao_manual.


@pytest.mark.asyncio
async def test_processar_extratos_pendentes_bpi_secao_intermedia_falha_forca_revisao_manual(
    db_session, monkeypatch
):
    # A secção do MEIO (não a última) da lista falha validação (saldo_inicial=None -> FalhaValidacao
    # de A-P3), mas a ÚLTIMA secção da lista valida com sucesso. Sem a correção, a última chamada a
    # _processar_extrato_extraido reescreveria documento.estado_validacao = "validado" por cima do
    # "revisao_manual" já escrito pela secção do meio — este teste prova que isso já não acontece.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline import extratos as extratos_module
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import alerta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    extrato_valido_primeiro = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem BPI",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("1200.00")),
        saldo_inicial=Decimal("1000.00"),
        movimentos=[MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("200.00"), descricao="mov 1")],
    )
    extrato_do_meio_falhado = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="poupanca",
        nome_conta="Poupança BPI",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("500.00")),
        saldo_inicial=None,  # A-P3: sem saldo_inicial o checksum é impossível -> FalhaValidacao
        movimentos=[],
    )
    extrato_valido_ultimo = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="divida",
        nome_conta="Crédito Pessoal",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("5000.00")),
        saldo_inicial=Decimal("5100.00"),
        movimentos=[MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("-100.00"), descricao="mov 2")],
    )

        # irrelevante (só precisa de não bater no parser banco_generico, que devolve None sem os
    # marcadores "Banco:"/"Conta:"/"Saldo em ... EUR").
    monkeypatch.setattr(
        extratos_module,
        "parse_banco_bpi",
        lambda texto_ocr: [extrato_valido_primeiro, extrato_do_meio_falhado, extrato_valido_ultimo],
    )

    paperless = FakePaperless(
        {41: "texto qualquer — parse_banco_bpi está monkeypatched"},
        tags_por_documento={41: [61]},
        mapa_tags={61: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 3))

    documento = await documento_repo.obter_por_paperless_id(db_session, 41)
    assert documento is not None
    # a prova central: a ÚLTIMA secção da lista validou, mas o estado final tem de refletir o
    # resultado AGREGADO (a secção do meio falhou) — não o resultado da última chamada.
    assert documento.estado_validacao == "revisao_manual"
    assert paperless.tags_removidas == []  # nem todas as secções validaram — tag não é removida

    alertas = await alerta_repo.listar_nao_enviados(db_session)
    assert len(alertas) == 1  # _alertar_revisao_manual é idempotente (chave_deduplicacao por documento)
    assert alertas[0].tipo == "documento_revisao_manual"


async def _contar_linhas_extrato(db_session, *, documento_id, conta_id):
    from sqlalchemy import select

    from ava.models.linha_extrato import LinhaExtrato

    result = await db_session.execute(
        select(LinhaExtrato).where(
            LinhaExtrato.documento_id == documento_id, LinhaExtrato.conta_id == conta_id
        )
    )
    return len(result.scalars().all())


# --- Achado CRÍTICO (revisão final Fase A): aprovação manual duplicava linhas já persistidas ---
#
# Reproduzido empiricamente pelo revisor contra Postgres real: só a secção "Depósitos à Ordem"
# tem checksum real (lê saldo_inicial do texto); as restantes derivam
# saldo_inicial = saldo_final − soma_movimentos, uma tautologia que nunca falha — na prática, é
# sempre a secção à ordem que falha e força o documento para revisao_manual, MAS as outras
# secções já validaram e JÁ PERSISTIRAM linha_extrato/saldo_historico antes disso (cada secção é
# persistida independentemente em processar_extratos_pendentes). Sem guard de idempotência,
# _aprovar_extrato_manualmente repersistia TODAS as secções (incluindo as já persistidas) quando
# o humano carrega em "Aprovar" — duplicando linha_extrato (sem unique constraint, ao contrário
# de saldo_historico) e, a jusante, duplicando o Movimento na reconciliação: dinheiro duplicado
# no ledger central, sem qualquer sinal (o documento acaba marcado "validado").
@pytest.mark.asyncio
async def test_aprovar_extrato_manualmente_nao_duplica_linhas_ja_persistidas(db_session, monkeypatch):
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.ingestion.pipeline import extratos as extratos_module
    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    # secção à ordem: única com checksum real -> falha de propósito (saldo_inicial=None, A-P3).
    extrato_a_ordem_falhado = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem BPI",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("1200.00")),
        saldo_inicial=None,
        movimentos=[
            MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("200.00"), descricao="mov a ordem")
        ],
    )
    # secções derivadas: checksum tautológico -> validam sempre, e por isso JÁ PERSISTEM antes de
    # o documento cair em revisao_manual por causa da secção à ordem.
    extrato_poupanca_valido = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="poupanca",
        nome_conta="Poupança BPI",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("500.00")),
        saldo_inicial=Decimal("450.00"),
        movimentos=[MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("50.00"), descricao="reforco")],
    )
    extrato_credito_valido = ExtratoBancario(
        instituicao="BPI",
        tipo_conta="divida",
        nome_conta="Crédito Pessoal",
        saldo_final=SaldoFinal(data=date(2026, 7, 3), valor=Decimal("5000.00")),
        saldo_inicial=Decimal("5100.00"),
        movimentos=[
            MovimentoExtraido(data=date(2026, 7, 1), valor=Decimal("-100.00"), descricao="amortizacao")
        ],
    )

    monkeypatch.setattr(
        extratos_module,
        "parse_banco_bpi",
        lambda texto_ocr: [extrato_a_ordem_falhado, extrato_poupanca_valido, extrato_credito_valido],
    )

    paperless = FakePaperless(
        {50: "texto qualquer — parse_banco_bpi está monkeypatched"},
        tags_por_documento={50: [70]},
        mapa_tags={70: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 7, 3))

    documento = await documento_repo.obter_por_paperless_id(db_session, 50)
    assert documento is not None
    assert documento.estado_validacao == "revisao_manual"  # a secção à ordem falhou o checksum
    assert paperless.tags_removidas == []  # nem tudo validou — tag ainda não é removida

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    # só as duas secções válidas persistiram conta+linha_extrato; a secção à ordem falhou ANTES
    # de _persistir_extrato ser chamado (FalhaValidacao em validar_extrato), logo nunca chegou a
    # criar a sua Conta.
    assert len(contas) == 2
    conta_poupanca = next(c for c in contas if c.tipo == "poupanca")
    conta_credito = next(c for c in contas if c.tipo == "divida")

    linhas_poupanca_antes = await _contar_linhas_extrato(
        db_session, documento_id=documento.id, conta_id=conta_poupanca.id
    )
    linhas_credito_antes = await _contar_linhas_extrato(
        db_session, documento_id=documento.id, conta_id=conta_credito.id
    )
    assert linhas_poupanca_antes == 1  # já persistida pela corrida automática
    assert linhas_credito_antes == 1

    # O humano vê o documento em /revisao e carrega em "Aprovar" — a única ação que a UI oferece.
    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=paperless)
    assert aprovado is True

    linhas_poupanca_depois = await _contar_linhas_extrato(
        db_session, documento_id=documento.id, conta_id=conta_poupanca.id
    )
    linhas_credito_depois = await _contar_linhas_extrato(
        db_session, documento_id=documento.id, conta_id=conta_credito.id
    )
    # a prova central: a contagem de linha_extrato para as contas já persistidas NÃO duplicou.
    # Sem a correção, isto falharia com 2 em vez de 1 (o dobro das linhas, dinheiro duplicado).
    assert linhas_poupanca_depois == 1
    assert linhas_credito_depois == 1

    # a secção à ordem (que nunca tinha sido persistida) foi criada agora, pela aprovação manual.
    contas_depois = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas_depois) == 3
    conta_a_ordem = next(c for c in contas_depois if c.tipo == "a_ordem")
    linhas_a_ordem = await _contar_linhas_extrato(
        db_session, documento_id=documento.id, conta_id=conta_a_ordem.id
    )
    assert linhas_a_ordem == 1

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"


def _dados_conta_bpi(
    *, tipo_conta: str, nome_conta: str, saldo_inicial: str, saldo_final_valor: str, movimento_valor: str
) -> dict:
    return {
        "instituicao": "BPI",
        "tipo_conta": tipo_conta,
        "nome_conta": nome_conta,
        "saldo_final": {"data": "2026-07-03", "valor": saldo_final_valor},
        "saldo_inicial": saldo_inicial,
        "movimentos": [{"data": "2026-07-01", "valor": movimento_valor, "descricao": "mov"}],
    }


@pytest.mark.asyncio
async def test_aprovar_extrato_manualmente_formato_multiconta_aprova_todas_as_contas(db_session):
    # dados_extraidos = {"contas": [...]} (formato BPI) — antes da correção,
    # ExtratoBancario.model_validate(dados_extraidos) levantava ValidationError para esta forma e
    # a função devolvia False sempre, sem nunca persistir nenhuma conta.
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    dados_conta_ordem = _dados_conta_bpi(
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem BPI",
        saldo_inicial="1000.00",
        saldo_final_valor="1200.00",
        movimento_valor="200.00",
    )
    dados_conta_poupanca = _dados_conta_bpi(
        tipo_conta="poupanca",
        nome_conta="Poupança BPI",
        saldo_inicial="450.00",
        saldo_final_valor="500.00",
        movimento_valor="50.00",
    )
    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=42,
        nivel_extracao=0,
        dados_extraidos={"contas": [dados_conta_ordem, dados_conta_poupanca]},
        estado_validacao="revisao_manual",
        registado_por=titular.id,
    )
    await db_session.commit()

    paperless = FakePaperless({})

    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=paperless)

    assert aprovado is True
    assert paperless.tags_removidas == [42]

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 2  # ambas as contas foram criadas, não só uma

    conta_ordem = next(c for c in contas if c.tipo == "a_ordem")
    conta_poupanca = next(c for c in contas if c.tipo == "poupanca")
    saldo_ordem = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_ordem.id)
    saldo_poupanca = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_poupanca.id)
    # confirma os SALDOS (não só a contagem de contas) — prova que cada item da lista foi
    # persistido com os dados corretos, não só que "algo" foi criado duas vezes.
    assert saldo_ordem.valor == Decimal("1200.00")
    assert saldo_poupanca.valor == Decimal("500.00")

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    assert documento_atualizado.estado_validacao == "validado"


@pytest.mark.asyncio
async def test_aprovar_extrato_manualmente_formato_multiconta_item_malformado_nao_bloqueia_as_restantes(
    db_session,
):
    # Uma das duas "contas" da lista não é um ExtratoBancario válido (falta instituicao,
    # tipo_conta, saldo_final, etc.). A conta válida tem de ser aprovada na mesma — um item
    # malformado individual não pode bloquear as restantes (mesmo princípio de A-P6) — mas o
    # documento não pode fingir sucesso total: fica em "revisao_manual" porque nem tudo validou.
    from ava.ingestion.pipeline import aprovar_documento_manualmente
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="conjuge")
    await db_session.commit()

    dados_conta_valida = _dados_conta_bpi(
        tipo_conta="a_ordem",
        nome_conta="Conta à Ordem BPI",
        saldo_inicial="1000.00",
        saldo_final_valor="1200.00",
        movimento_valor="200.00",
    )
    dados_conta_malformada = {"isto": "nao e um ExtratoBancario"}

    documento = await documento_repo.criar_documento(
        db_session,
        paperless_document_id=43,
        nivel_extracao=0,
        dados_extraidos={"contas": [dados_conta_valida, dados_conta_malformada]},
        estado_validacao="revisao_manual",
        registado_por=titular.id,
    )
    await db_session.commit()

    paperless = FakePaperless({})

    aprovado = await aprovar_documento_manualmente(db_session, documento_id=documento.id, paperless=paperless)

    assert aprovado is True  # a conta válida foi aprovada mesmo com a outra malformada

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    assert len(contas) == 1  # só a conta válida foi persistida — a malformada foi descartada
    saldo = await saldo_historico_repo.obter_saldo_mais_recente(db_session, contas[0].id)
    assert saldo.valor == Decimal("1200.00")

    documento_atualizado = await documento_repo.obter_por_id(db_session, documento.id)
    # não finge sucesso total: uma das duas contas não validou, o documento continua sinalizado
    assert documento_atualizado.estado_validacao == "revisao_manual"


# Os testes de finalizar_despesa_avulsa / finalizar_rendimento_avulso viviam aqui. Saíram com
# ava.ingestion.pipeline.telegram: esses tipos de item de fila eram produzidos apenas pelo bot
# do Telegram (removido). O registo rápido equivalente é agora ava.financas.registo_rapido,
# que cria o movimento diretamente, sem passar pela fila do LLM.


async def _processar_recibo_de_teste(
    db_session, *, titular_id, cartao_refeicao: Decimal, mes: int, ano: int
) -> None:
    """Simula o caminho nível-1 de um recibo de vencimento: não existe parser nível-0 para
    recibos (ao contrário de faturas/extratos), por isso o único caminho real é sempre um item
    de fila já "concluido" com o resultado_json que o worker devolveria, seguido de
    finalizar_recibo_vencimento — o mesmo padrão que os testes de fatura/extrato nível-1 já usam
    acima."""
    from ava.ingestion.pipeline import finalizar_recibo_vencimento

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=950, nivel_extracao=1, dados_extraidos={}, registado_por=titular_id
    )
    item = await fila_repo.criar_item(
        db_session, documento_id=documento.id, texto_ocr="recibo de vencimento", tipo="recibo_vencimento"
    )
    await fila_repo.concluir(
        db_session,
        item.id,
        {
            "cartao_refeicao": str(cartao_refeicao),
            "entidade_patronal": "Empresa Teste",
            "mes_referencia": mes,
            "ano_referencia": ano,
        },
    )
    await db_session.flush()

    await finalizar_recibo_vencimento(
        db_session, item_id=item.id, paperless=FakePaperless({}), referencia=date(ano, mes, 1)
    )


@pytest.mark.asyncio
async def test_recibo_com_cartao_refeicao_nao_escreve_ancora(db_session):
    # REGRESSAO de §7.2: o recibo escrevia o movimento de carregamento E uma ancora calculada a
    # partir dele. Uma ancora calculada a partir do razao nao pode desmentir o razao. Alem
    # disso a linha importava `saldo_historico_repo.criar`, que nao existe -- qualquer recibo
    # com cartao de refeicao levantava ImportError antes de criar o movimento.
    from sqlalchemy import select

    from ava.models.movimento import Movimento
    from ava.models.saldo_historico import SaldoHistorico
    from tests.fabricas import criar_conta as fabrica_criar_conta, criar_titular_e_conta

    titular, _conta_padrao = await criar_titular_e_conta(db_session)
    cartao = await fabrica_criar_conta(
        db_session, titular=titular, tipo="cartao_refeicao", nome="Cartão Refeição - aa-stop-run"
    )
    await db_session.commit()

    await _processar_recibo_de_teste(
        db_session, titular_id=titular.id, cartao_refeicao=Decimal("180.59"), mes=5, ano=2026
    )
    await db_session.commit()

    movimentos = await db_session.execute(
        select(Movimento).where(Movimento.conta_id == cartao.id)
    )
    assert len(movimentos.scalars().all()) == 1

    ancoras = await db_session.execute(
        select(SaldoHistorico).where(SaldoHistorico.conta_id == cartao.id)
    )
    assert ancoras.scalars().all() == []


# --- Spec 2026-08-13: a guarda de reingestão de extrato passa a ser por LINHA, não por
# DOCUMENTO --- Tarefa 1.
#
# O incidente de 2026-08-13: o mesmo extrato do BPI entrou pela pasta sincronizada e depois por
# mail, em documentos paperless diferentes, e a guarda antiga (existe_para_documento_e_conta,
# indexada a documento_id) não via a segunda cópia — duplicou 135 movimentos. Os testes abaixo
# provam a guarda nova (contar_existentes_por_chave, indexada a (conta_id, data, valor)) contra
# esse incidente e contra os casos que a guarda antiga já cobria.


@pytest.mark.asyncio
async def test_mesmo_extrato_em_dois_documentos_nao_duplica_linhas(db_session):
    # O incidente de 2026-08-13: o mesmo extrato do BPI entrou pela pasta sincronizada e depois
    # por mail, em documentos diferentes, e duplicou 135 movimentos. A guarda antiga era indexada
    # ao documento_id e não podia ver a segunda cópia.
    #
    # A asserção sobre a PRIMEIRA ingestão é o controlo positivo e é obrigatória: sem ela, um
    # pipeline que não criasse nada em nenhuma das duas passagens passava neste teste.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    movimentos = [
        MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal("-30.00"), descricao="COMPRA A"),
        MovimentoExtraido(data=date(2026, 7, 11), valor=Decimal("-45.50"), descricao="COMPRA B"),
    ]

    def _extrato():
        return ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-75.50")),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos,
        )

    primeiro = await documento_repo.criar_documento(
        db_session, paperless_document_id=901, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=primeiro, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    linhas_apos_primeira = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 10), ate=date(2026, 8, 3)
    )
    assert sum(linhas_apos_primeira.values()) == 2

    segundo = await documento_repo.criar_documento(
        db_session, paperless_document_id=902, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=segundo, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    linhas_apos_segunda = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 10), ate=date(2026, 8, 3)
    )
    assert sum(linhas_apos_segunda.values()) == 2


@pytest.mark.asyncio
async def test_segundo_documento_mais_completo_cria_so_o_que_falta(db_session):
    # O caso real: o documento 3 trazia 06/07-03/08 e o 59 trazia 04/07-03/08. O certo é ficar
    # com a união — as linhas sobrepostas saltadas, as novas criadas.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    curto = [MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal("-30.00"), descricao="B")]
    completo = [
        MovimentoExtraido(data=date(2026, 7, 8), valor=Decimal("-12.00"), descricao="A"),
        MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal("-30.00"), descricao="B"),
    ]

    def _extrato(movs):
        return ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-42.00")),
            saldo_inicial=Decimal("0.00"), movimentos=movs,
        )

    primeiro = await documento_repo.criar_documento(
        db_session, paperless_document_id=903, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=primeiro, extrato=_extrato(curto),
        movimentos=curto, titular_id=titular.id,
    )
    await db_session.commit()

    segundo = await documento_repo.criar_documento(
        db_session, paperless_document_id=904, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=segundo, extrato=_extrato(completo),
        movimentos=completo, titular_id=titular.id,
    )
    await db_session.commit()

    contagem = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 8), ate=date(2026, 8, 3)
    )
    assert contagem[(date(2026, 7, 8), Decimal("-12.00"))] == 1
    assert contagem[(date(2026, 7, 10), Decimal("-30.00"))] == 1
    assert sum(contagem.values()) == 2


@pytest.mark.asyncio
async def test_duas_transacoes_iguais_no_mesmo_dia_nao_colapsam(db_session):
    # Em produção há quatro grupos assim só em Julho (dois levantamentos de 10,00 € no mesmo dia,
    # referências ATM diferentes). Uma guarda por existência em vez de por multiplicidade
    # apagava a segunda — falta dinheiro no razão, que é pior de detetar do que sobrar.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    movimentos = [
        MovimentoExtraido(data=date(2026, 7, 23), valor=Decimal("-10.00"), descricao="LEV ATM /27"),
        MovimentoExtraido(data=date(2026, 7, 23), valor=Decimal("-10.00"), descricao="LEV ATM /29"),
    ]

    def _extrato():
        return ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-20.00")),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos,
        )

    primeiro = await documento_repo.criar_documento(
        db_session, paperless_document_id=905, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=primeiro, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    contagem = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 23), ate=date(2026, 8, 3)
    )
    assert contagem[(date(2026, 7, 23), Decimal("-10.00"))] == 2

    segundo = await documento_repo.criar_documento(
        db_session, paperless_document_id=906, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=segundo, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    contagem = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 23), ate=date(2026, 8, 3)
    )
    assert contagem[(date(2026, 7, 23), Decimal("-10.00"))] == 2


@pytest.mark.asyncio
async def test_uma_existente_e_duas_no_extrato_salta_a_primeira_cria_a_segunda(db_session):
    # Spec §7, quarto ponto: o caso assimétrico M=1,N=2 — uma linha já existe na base e o extrato
    # traz DUAS linhas com a MESMA chave. A primeira ocorrência tem de ser saltada (já existia) e
    # a segunda criada (é a transação nova genuína). Nenhum dos outros testes da guarda cobre esta
    # assimetria: M=0,N=1 / M=0,N=2 / M=1,N=1 / M=2,N=2 não distinguem "salta a primeira, cria a
    # segunda" de "salta a segunda, cria a primeira" — a contagem final (2: a que já existia mais
    # a única genuinamente nova) já provaria o resultado agregado, mas resumo_ingestao
    # (criadas=1, saltadas=1) prova a ordem exata — a mesma conta do exemplo trabalhado na spec
    # §4.2 ("o total fica em duas, que é o certo").
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    movimento_x = MovimentoExtraido(
        data=date(2026, 7, 23), valor=Decimal("-10.00"), descricao="LEV ATM /27"
    )

    primeiro = await documento_repo.criar_documento(
        db_session, paperless_document_id=909, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session,
        documento=primeiro,
        extrato=ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-10.00")),
            saldo_inicial=Decimal("0.00"), movimentos=[movimento_x],
        ),
        movimentos=[movimento_x],
        titular_id=titular.id,
    )
    await db_session.commit()

    segundo = await documento_repo.criar_documento(
        db_session, paperless_document_id=910, nivel_extracao=0, dados_extraidos={}
    )
    movimentos_segundo = [movimento_x, movimento_x]
    await _persistir_extrato(
        db_session,
        documento=segundo,
        extrato=ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-20.00")),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos_segundo,
        ),
        movimentos=movimentos_segundo,
        titular_id=titular.id,
    )
    await db_session.commit()

    contagem = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 23), ate=date(2026, 8, 3)
    )
    assert contagem[(date(2026, 7, 23), Decimal("-10.00"))] == 2

    assert segundo.resumo_ingestao == {
        "contas": [{"conta": "Ordem", "criadas": 1, "saltadas": 1}]
    }


@pytest.mark.asyncio
async def test_reaprovar_o_mesmo_documento_nao_duplica(db_session):
    # TRANSITADO da guarda removida (existe_para_documento_e_conta, achado Crítico da revisão da
    # Fase A): a aprovação manual de um documento BPI multi-secção repersiste TODAS as secções,
    # incluindo as que já tinham validado. A guarda nova tem de continuar a cobrir isto — se não
    # cobrisse, esta mudança seria uma proteção apagada, não substituída.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, linha_extrato_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    movimentos = [
        MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal("-30.00"), descricao="COMPRA A")
    ]
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=907, nivel_extracao=0, dados_extraidos={}
    )

    def _extrato():
        return ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-30.00")),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos,
        )

    for _ in range(2):
        await _persistir_extrato(
            db_session, documento=documento, extrato=_extrato(), movimentos=movimentos,
            titular_id=titular.id,
        )
        await db_session.commit()

    contagem = await linha_extrato_repo.contar_existentes_por_chave(
        db_session, conta_id=conta.id, de=date(2026, 7, 10), ate=date(2026, 8, 3)
    )
    assert sum(contagem.values()) == 1


@pytest.mark.asyncio
async def test_seccao_sem_movimentos_nao_rebenta(db_session):
        # o intervalo [min(data), saldo_final.data] não existe. A guarda tem de sair de cena e a
    # âncora tem de continuar a gravar-se — este é o controlo positivo.
    from ava.extraction.schema_extrato import ExtratoBancario, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    conta = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BBVA", tipo="divida", nome="Crédito Auto"
    )
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=908, nivel_extracao=0, dados_extraidos={}
    )
    extrato = ExtratoBancario(
        instituicao="BBVA", tipo_conta="divida", nome_conta="Crédito Auto",
        saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("1958.47")),
        saldo_inicial=Decimal("1958.47"), movimentos=[],
    )

    await _persistir_extrato(
        db_session, documento=documento, extrato=extrato, movimentos=[],
        titular_id=titular.id, resolver_por_nome=True,
    )
    await db_session.commit()

    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta.id)
    assert ancora.valor == Decimal("1958.47")
    assert ancora.origem == "extrato"


@pytest.mark.asyncio
async def test_resumo_ingestao_regista_criadas_e_saltadas_por_conta(db_session):
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import conta_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="BPI", tipo="a_ordem", nome="Ordem"
    )
    await db_session.commit()

    movimentos = [
        MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal("-30.00"), descricao="A"),
        MovimentoExtraido(data=date(2026, 7, 11), valor=Decimal("-45.50"), descricao="B"),
    ]

    def _extrato():
        return ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta="Ordem",
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal("-75.50")),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos,
        )

    primeiro = await documento_repo.criar_documento(
        db_session, paperless_document_id=911, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=primeiro, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    assert primeiro.resumo_ingestao == {
        "contas": [{"conta": "Ordem", "criadas": 2, "saltadas": 0}]
    }

    segundo = await documento_repo.criar_documento(
        db_session, paperless_document_id=912, nivel_extracao=0, dados_extraidos={}
    )
    await _persistir_extrato(
        db_session, documento=segundo, extrato=_extrato(), movimentos=movimentos,
        titular_id=titular.id,
    )
    await db_session.commit()

    assert segundo.resumo_ingestao == {
        "contas": [{"conta": "Ordem", "criadas": 0, "saltadas": 2}]
    }


@pytest.mark.asyncio
async def test_resumo_ingestao_acumula_uma_entrada_por_seccao(db_session):
    # Um "Extracto Integrado" do BPI traz várias secções e chama _persistir_extrato uma vez por
    # conta, com o MESMO documento. Cada chamada tem de acrescentar à lista, não substituí-la.
    from ava.extraction.schema_extrato import ExtratoBancario, MovimentoExtraido, SaldoFinal
    from ava.ingestion.pipeline.extratos import _persistir_extrato
    from ava.repositories import titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await db_session.commit()

    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=913, nivel_extracao=0, dados_extraidos={}
    )

    for nome, valor in (("Ordem", "-30.00"), ("Poupança", "-12.00")):
        movimentos = [
            MovimentoExtraido(data=date(2026, 7, 10), valor=Decimal(valor), descricao="X")
        ]
        extrato = ExtratoBancario(
            instituicao="BPI", tipo_conta="a_ordem", nome_conta=nome,
            saldo_final=SaldoFinal(data=date(2026, 8, 3), valor=Decimal(valor)),
            saldo_inicial=Decimal("0.00"), movimentos=movimentos,
        )
        await _persistir_extrato(
            db_session, documento=documento, extrato=extrato, movimentos=movimentos,
            titular_id=titular.id, resolver_por_nome=True,
        )
    await db_session.commit()

    assert documento.resumo_ingestao == {
        "contas": [
            {"conta": "Ordem", "criadas": 1, "saltadas": 0},
            {"conta": "Poupança", "criadas": 1, "saltadas": 0},
        ]
    }


@pytest.mark.asyncio
async def test_processar_extrato_trade_republic_encontra_conta_existente_sem_duplicar(db_session):
    # A conta Trade Republic é criada manualmente pelo utilizador ANTES de qualquer extrato ser
    # importado (não há caminho de multi-conta como o BPI — spec: "só esta conta cash, por
    # agora"). _persistir_extrato passa SEMPRE nome=extrato.nome_conta a
    # obter_ou_criar_por_instituicao, mesmo no caminho de conta única — nunca nome=None — por
    # isso a conta só é encontrada, e não duplicada, se o NOME bater exatamente com o que o
    # parser produz ("Checking Account"). O utilizador tem de nomear a conta assim.
    from pathlib import Path

    from ava.ingestion.pipeline import processar_extratos_pendentes
    from ava.repositories import conta_repo, saldo_historico_repo, titular_repo

    titular = await titular_repo.criar_titular(db_session, nome="aa-stop-run", tipo="proprio")
    await db_session.flush()
    conta_existente = await conta_repo.criar_conta(
        db_session, titular_id=titular.id, instituicao="Trade Republic", tipo="a_ordem",
        nome="Checking Account",
    )
    await db_session.commit()

    texto = (
        Path(__file__).parent.parent / "test_extraction" / "fixtures" / "extrato_trade_republic.txt"
    ).read_text(encoding="utf-8")
    paperless = FakePaperless(
        {30: texto},
        tags_por_documento={30: [50]},
        mapa_tags={50: f"telegram-titular-{titular.id}"},
    )

    await processar_extratos_pendentes(db_session, paperless, referencia=date(2026, 8, 14))

    contas = await conta_repo.listar_por_titular(db_session, titular.id)
    contas_trade_republic = [c for c in contas if c.instituicao == "Trade Republic"]
    assert len(contas_trade_republic) == 1
    assert contas_trade_republic[0].id == conta_existente.id

    ancora = await saldo_historico_repo.obter_saldo_mais_recente(db_session, conta_existente.id)
    assert ancora is not None
    assert ancora.valor == Decimal("396.37")
    assert ancora.origem == "extrato"
