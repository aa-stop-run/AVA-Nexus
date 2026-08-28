import calendar
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import _contar_alertas, _parse_filtros_movimentos, templates
from ava.db import get_session
from ava.financas.categorizacao_automatica import padrao_de_descricao
from ava.financas.deteccao_outlier import avaliar_outlier
from ava.financas.registo_rapido import registar_movimento_rapido
from ava.financas.saldos import TIPOS_PASSIVO, parse_valor_pt
from ava.ingestion.reconciliacao import (
    categorizar_transferencia,
    desfazer_movimento,
    ignorar_linha,
    resolver_como_despesa,
    resolver_como_rendimento,
    resolver_como_transferencia,
)
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.models.ressarcimento import Ressarcimento
from ava.repositories import (
    ativo_repo,
    categoria_repo,
    conta_repo,
    linha_extrato_repo,
    movimento_repo,
    recorrente_repo,
    ressarcimento_repo,
    titular_repo,
)

router = APIRouter(tags=["movimentos"])

# Categorias onde um cartão de refeição pode legalmente ser usado (spec 2026-08-08 §1.1: só
# supermercado, restaurante e café) -- oferecer as restantes no formulário seria dar a escolher
# uma categoria que a própria despesa não pode ter tido (achado de 2026-08-20).
CATEGORIAS_CARTAO_REFEICAO = ("Supermercado", "Restaurantes", "Café")


@router.post("/movimentos/{movimento_id}/desfazer", response_class=HTMLResponse)
async def desfazer_movimento_route(
    movimento_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    desfeito = await desfazer_movimento(session, movimento_id=movimento_id)
    if not desfeito:
        raise HTTPException(status_code=404, detail="movimento não encontrado")
    return templates.TemplateResponse(request, "movimento_desfeito.html", {})


@router.get("/movimentos")
async def movimentos(
    request: Request,
    busca: str | None = None,
    valor_min: str | None = None,
    valor_max: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    mes_ano: str | None = None,
    tipo_movimento: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    filtros = _parse_filtros_movimentos(
        busca=busca,
        valor_min=valor_min,
        valor_max=valor_max,
        data_inicio=data_inicio,
        data_fim=data_fim,
        mes_ano=mes_ano,
        tipo_movimento=tipo_movimento,
    )
    # `tipo_movimento` não é filtro de linha_extrato (o sinal do valor é que distingue
    # despesa/rendimento lá) — passá-lo rebentaria com TypeError. Fica só para os movimentos.
    filtros_linhas = {
        chave: valor for chave, valor in filtros.items() if chave != "tipo_movimento"
    }
    pendentes = await linha_extrato_repo.listar_em_revisao_manual(
        session, **filtros_linhas
    )

    # Uma entrada por linha pendente, sem agregação. O agrupamento por comerciante existia para a
    # importação histórica em massa, que já está feita; com vários veículos, resolver o grupo
    # atribuía os abastecimentos todos ao mesmo carro (ver a spec 2026-08-06).
    entradas: list[dict] = [
        {
            "linha_id": linha.id,
            "data": linha.data,
            "descricao": linha.descricao,
            "valor": abs(linha.valor),
            "tipo": "saida" if linha.valor < 0 else "entrada",
        }
        for linha in pendentes
    ]

    # Movimentos registados à mão (/registo, /registo-rapido) que ficaram sem categoria.
    # Cobre também as origens históricas — ver movimento_repo.ORIGENS_REGISTO_MANUAL:
    # sem isso, os que ficaram por categorizar desapareciam desta página.
    #
    # ORIGENS_CATEGORIZAVEIS (não ORIGENS_REGISTO_MANUAL sozinha) inclui também "ficheiro": um
    # movimento importado do BPI Net sem padrão aprendido é tão por-categorizar como um manual —
    # sem isto, ficava invisível aqui e sem contar para orçamento nenhum (revisão final da spec
    # 2026-08-09, achado 1).
    #
    # Lê de `filtros` (já validado e convertido por _parse_filtros_movimentos), NUNCA dos
    # parâmetros crus da query string: estes são todos `str`, e um "abc" em valor_min ou uma data
    # fora de ISO chegavam intactos ao SQL, onde o Postgres rebentava com "operator does not
    # exist: numeric >= character varying" e a página devolvia 500. O contrato desta página é o
    # oposto — filtro malformado é ignorado em silêncio (ver a docstring de
    # _parse_filtros_movimentos). `mes_ano` também já vem resolvido para data_inicio/data_fim lá.
    condicoes_manuais = [
        Movimento.origem.in_(movimento_repo.ORIGENS_CATEGORIZAVEIS),
        MovimentoLinha.categoria_id.is_(None),
    ]
    if "busca" in filtros:
        condicoes_manuais.append(Movimento.descricao.ilike(f"%{filtros['busca']}%"))
    if "valor_min" in filtros:
        condicoes_manuais.append(Movimento.valor >= filtros["valor_min"])
    if "valor_max" in filtros:
        condicoes_manuais.append(Movimento.valor <= filtros["valor_max"])
    if "data_inicio" in filtros:
        condicoes_manuais.append(Movimento.data >= filtros["data_inicio"])
    if "data_fim" in filtros:
        condicoes_manuais.append(Movimento.data <= filtros["data_fim"])
    if filtros.get("tipo_movimento") in ("saida", "entrada"):
        condicoes_manuais.append(Movimento.tipo == filtros["tipo_movimento"])

    resultado_manuais = await session.execute(
        select(Movimento)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .where(*condicoes_manuais)
    )
    for mov in resultado_manuais.scalars().unique():
        entradas.append(
            {
                "movimento_id": mov.id,
                "data": mov.data,
                "descricao": mov.descricao,
                "valor": mov.valor,
                "tipo": "saida" if mov.tipo == "saida" else "entrada",
                "is_manual": True,
                # Pré-seleção do <select> de conta em movimentos.html: um movimento de ficheiro
                # já tem a conta autoritativa (a escolhida na importação), e mostrar qual é evita
                # o utilizador ter de adivinhar de uma lista às cegas (revisão da revisão final,
                # achado 1). None num movimento manual antigo sem conta — o template já trata
                # "nenhuma pré-seleção" como o comportamento anterior.
                "conta_id": mov.conta_id,
            }
        )

    # Mais recentes primeiro: é a ordem por que o utilizador as reconhece.
    entradas.sort(key=lambda entrada: entrada["data"], reverse=True)

    # Todas as transferências sem categoria — agrupadas por conta de destino.
    # Inclui créditos (amortizações) e transferências genéricas (poupança, etc.).
    # Sem "busca" (a descrição é sempre o mesmo literal, filtrar por texto não distingue nada) e
    # sem "tipo_movimento" (uma transferência não é saída nem entrada) — nenhum dos dois é
    # parâmetro de listar_transferencias_sem_categoria, e passá-los dá TypeError.
    filtros_transferencia = {
        chave: valor
        for chave, valor in filtros.items()
        if chave not in ("busca", "tipo_movimento")
    }
    grupos_transferencia: dict[uuid.UUID | str, dict] = {}
    for mov in await movimento_repo.listar_transferencias_sem_categoria(
        session, **filtros_transferencia
    ):
        desc_upper = mov.descricao.upper() if mov.descricao else ""
        if (
            "AMORTIZACAO" in desc_upper
            or "JUROS" in desc_upper
            or "PRESTACAO" in desc_upper
        ):
            chave_grupo = mov.conta_destino_id or f"sem_destino_{mov.descricao}"
        else:
            chave_grupo = (
                mov.conta_destino_id
                or f"sem_destino_{padrao_de_descricao(mov.descricao)}"
            )

        grupo = grupos_transferencia.setdefault(
            chave_grupo,
            {
                "movimento_id": mov.id,
                "linha_id": mov.linha_extrato_id,
                "conta_destino_id": mov.conta_destino_id,
                "descricao": mov.descricao or "Transferência",
                "quantidade": 0,
                "total": Decimal("0"),
            },
        )
        grupo["quantidade"] += 1
        grupo["total"] += mov.valor

    lista_transferencias = []
    for grupo in grupos_transferencia.values():
        conta_destino = (
            await conta_repo.obter_por_id(session, grupo["conta_destino_id"])
            if grupo["conta_destino_id"]
            else None
        )

        is_entrada = False
        if conta_destino and conta_destino.tipo in ["a_ordem", "poupanca"]:
            is_entrada = True

        if not is_entrada:
            grupo["total"] = -grupo["total"]

        lista_transferencias.append(
            {
                **grupo,
                "conta_nome": (
                    conta_destino.nome
                    if conta_destino is not None
                    else grupo["descricao"]
                ),
            }
        )
    lista_transferencias.sort(key=lambda g: abs(g["total"]), reverse=True)

    categorias_despesa = await categoria_repo.listar_grupos_com_categorias(
        session, tipo="despesa"
    )
    categorias_receita = await categoria_repo.listar_grupos_com_categorias(
        session, tipo="receita"
    )
    contas = await conta_repo.listar_todas_ativas(session)
    ativos_lista = await ativo_repo.listar_todos_ativos(session)
    creditos_lista = [c for c in contas if c.tipo in TIPOS_PASSIVO]

    return templates.TemplateResponse(
        request,
        "movimentos.html",
        {
            "entradas": entradas,
            "transferencias": lista_transferencias,
            "categorias_despesa": categorias_despesa,
            "categorias_receita": categorias_receita,
            "contas_transferencia": contas,
            "ativos": ativos_lista,
            "creditos": creditos_lista,
            "filtros_form": {
                "busca": busca or "",
                "valor_min": valor_min or "",
                "valor_max": valor_max or "",
                "data_inicio": data_inicio or "",
                "data_fim": data_fim or "",
                "mes_ano": mes_ano or "",
                "tipo_movimento": tipo_movimento or "",
            },
            "total_alertas": await _contar_alertas(session),
        },
    )


@router.get("/movimentos/outlier-check", response_class=HTMLResponse)
async def movimentos_outlier_check(
    request: Request,
    categoria_id: str = "",
    valor: str = "",
    session: AsyncSession = Depends(get_session),
):
    try:
        cat_id = uuid.UUID(categoria_id)
        valor_dec = Decimal(valor)
    except (ValueError, InvalidOperation):
        return HTMLResponse("")

    categoria = await categoria_repo.obter_por_id(session, cat_id)
    if categoria is None:
        return HTMLResponse("")

    historico = await movimento_repo.historico_valores_categoria(session, cat_id)
    mensagem = avaliar_outlier(valor_dec, historico, categoria_nome=categoria.nome)
    if mensagem is None:
        return HTMLResponse("")

    return templates.TemplateResponse(
        request, "_outlier_hint.html", {"mensagem": mensagem}
    )


@router.get("/categorias/{categoria_id}/movimentos", response_class=HTMLResponse)
async def categoria_movimentos(
    categoria_id: uuid.UUID,
    request: Request,
    periodo: str | None = None,
    titular_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    if periodo:
        try:
            ano_pedido, mes_pedido = (int(parte) for parte in periodo.split("-"))
            date(ano_pedido, mes_pedido, 1)
        except (ValueError, TypeError):
            pass
        else:
            ano, mes = ano_pedido, mes_pedido
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    try:
        tid = uuid.UUID(titular_id) if titular_id else None
    except ValueError:
        tid = None

    movimentos_lista = await movimento_repo.listar_por_categoria(
        session, categoria_id=categoria_id, inicio=inicio, fim=fim, titular_id=tid
    )
    return templates.TemplateResponse(
        request,
        "_categoria_movimentos.html",
        {"movimentos": movimentos_lista, "categoria_id": categoria_id},
    )


@router.get("/movimentos/{movimento_id}/trocar-categoria-form", response_class=HTMLResponse)
async def trocar_categoria_form_route(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    mov = await movimento_repo.obter_por_id(session, movimento_id)
    if mov is None:
        raise HTTPException(status_code=404, detail="movimento não encontrado")

    categorias_despesa = await categoria_repo.listar_grupos_com_categorias(session, tipo="despesa")
    m_info = {
        "movimento_id": mov.id,
        "data": mov.data,
        "descricao": mov.descricao,
        "valor": mov.valor,
    }
    return templates.TemplateResponse(
        request,
        "_categoria_movimento_edit.html",
        {
            "m": m_info,
            "categoria_id": categoria_id,
            "categorias_despesa": categorias_despesa,
        },
    )


@router.post("/movimentos/{movimento_id}/trocar-categoria", response_class=HTMLResponse)
async def trocar_categoria_route(
    movimento_id: uuid.UUID,
    request: Request,
    nova_categoria_id: uuid.UUID = Form(...),
    session: AsyncSession = Depends(get_session),
):
    mov = await movimento_repo.obter_por_id(session, movimento_id)
    if mov is None:
        raise HTTPException(status_code=404, detail="movimento não encontrado")

    nova_categoria = await categoria_repo.obter_por_id(session, nova_categoria_id)
    if nova_categoria is None:
        raise HTTPException(status_code=404, detail="categoria não encontrada")

    for linha in mov.linhas:
        linha.categoria_id = nova_categoria_id

    await session.commit()
    return templates.TemplateResponse(
        request,
        "_categoria_movimento_trocado.html",
        {"nova_categoria": nova_categoria},
    )


@router.get("/movimentos/{movimento_id}/linha-categoria", response_class=HTMLResponse)
async def linha_categoria_route(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    mov = await movimento_repo.obter_por_id(session, movimento_id)
    if mov is None:
        raise HTTPException(status_code=404, detail="movimento não encontrado")

    m_info = {
        "movimento_id": mov.id,
        "data": mov.data,
        "descricao": mov.descricao,
        "valor": mov.valor,
    }
    return templates.TemplateResponse(
        request,
        "_categoria_movimento_item.html",
        {"m": m_info, "categoria_id": categoria_id},
    )


@router.post("/movimentos/{movimento_id}/despesa", response_class=HTMLResponse)
async def resolver_movimento_despesa(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: uuid.UUID = Form(...),
    ativo_id: uuid.UUID | None = Form(None),
    conta_relacionada_id: uuid.UUID | None = Form(None),
    leitura_odometro: int | None = Form(None),
    quantidade: Decimal | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    resolvido = await resolver_como_despesa(
        session,
        linha_id=movimento_id,
        categoria_id=categoria_id,
        ativo_id=ativo_id,
        conta_relacionada_id=conta_relacionada_id,
        leitura_odometro=leitura_odometro,
        quantidade=quantidade,
    )
    if not resolvido:
        raise HTTPException(
            status_code=404, detail="movimento não encontrado ou já resolvido"
        )
    return templates.TemplateResponse(request, "movimento_linha_resolvido.html", {})


@router.post("/movimentos/{movimento_id}/ativo", response_class=HTMLResponse)
async def atribuir_ativo_ao_movimento(
    movimento_id: uuid.UUID,
    request: Request,
    ativo_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    movimento = await session.get(Movimento, movimento_id)
    if movimento is None or movimento.tipo != "saida":
        raise HTTPException(status_code=404, detail="despesa não encontrada")

    novo_ativo_id = None
    if ativo_id.strip():
        try:
            novo_ativo_id = uuid.UUID(ativo_id.strip())
        except ValueError:
            raise HTTPException(status_code=404, detail="ativo não encontrado")
        if await ativo_repo.obter_por_id(session, novo_ativo_id) is None:
            raise HTTPException(status_code=404, detail="ativo não encontrado")

    resultado = await session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento_id)
    )
    for linha in resultado.scalars().all():
        linha.ativo_id = novo_ativo_id

    await session.commit()

    ativos_disponiveis = await ativo_repo.listar_todos_ativos(session)
    return templates.TemplateResponse(
        request,
        "_ativo_cell.html",
        {
            "movimento_id": movimento_id,
            "ativo_id_atual": novo_ativo_id,
            "ativos_disponiveis": ativos_disponiveis,
        },
    )


@router.post("/movimentos/{movimento_id}/credito", response_class=HTMLResponse)
async def ligar_movimento_ao_credito(
    movimento_id: uuid.UUID,
    request: Request,
    conta_relacionada_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    movimento = await session.get(Movimento, movimento_id)
    if movimento is None or movimento.tipo != "saida":
        raise HTTPException(status_code=404, detail="despesa não encontrada")

    nova_conta_id = None
    if conta_relacionada_id.strip():
        try:
            nova_conta_id = uuid.UUID(conta_relacionada_id.strip())
        except ValueError:
            raise HTTPException(
                status_code=404, detail="conta de dívida não encontrada"
            )
        conta = await conta_repo.obter_por_id(session, nova_conta_id)
        if conta is None or conta.tipo not in TIPOS_PASSIVO:
            raise HTTPException(
                status_code=404, detail="conta de dívida não encontrada"
            )

    resultado = await session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento_id)
    )
    for linha in resultado.scalars().all():
        linha.conta_relacionada_id = nova_conta_id

    await session.commit()

    creditos_disponiveis = await conta_repo.listar_dividas_ativas(session)
    return templates.TemplateResponse(
        request,
        "_credito_cell.html",
        {
            "movimento_id": movimento_id,
            "conta_relacionada_id_atual": nova_conta_id,
            "creditos_disponiveis": creditos_disponiveis,
        },
    )


@router.post(
    "/movimentos/{movimento_id}/ressarcimento", response_class=HTMLResponse
)
async def ligar_movimento_a_ressarcimento(
    movimento_id: uuid.UUID,
    request: Request,
    ressarcimento_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    movimento = await session.get(Movimento, movimento_id)
    if movimento is None or movimento.tipo not in ("saida", "entrada"):
        raise HTTPException(status_code=404, detail="movimento não encontrado")

    novo_ressarcimento_id: uuid.UUID | None
    if not ressarcimento_id.strip():
        novo_ressarcimento_id = None
    elif ressarcimento_id.strip() == "novo":
        grupo = await ressarcimento_repo.criar(session)
        novo_ressarcimento_id = grupo.id
    else:
        try:
            novo_ressarcimento_id = uuid.UUID(ressarcimento_id.strip())
        except ValueError:
            raise HTTPException(
                status_code=404, detail="grupo de ressarcimento não encontrado"
            )
        if await session.get(Ressarcimento, novo_ressarcimento_id) is None:
            raise HTTPException(
                status_code=404, detail="grupo de ressarcimento não encontrado"
            )

    resultado = await session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento_id)
    )
    for linha in resultado.scalars().all():
        linha.ressarcimento_id = novo_ressarcimento_id

    await session.commit()

    ressarcimentos_disponiveis = await ressarcimento_repo.listar_recentes(session)

    if novo_ressarcimento_id is not None:
        ids_na_lista = [grupo.id for grupo, _ in ressarcimentos_disponiveis]
        if novo_ressarcimento_id not in ids_na_lista:
            grupo_atual = await session.get(Ressarcimento, novo_ressarcimento_id)
            if grupo_atual is not None:
                resumo_atual = await ressarcimento_repo.resumo(
                    session, novo_ressarcimento_id
                )
                ressarcimentos_disponiveis = [
                    (grupo_atual, resumo_atual)
                ] + ressarcimentos_disponiveis

    response = templates.TemplateResponse(
        request,
        "_ressarcimento_cell.html",
        {
            "movimento_id": movimento_id,
            "ressarcimento_id_atual": novo_ressarcimento_id,
            "ressarcimentos_disponiveis": ressarcimentos_disponiveis,
        },
    )
    response.headers["HX-Refresh"] = "true"
    return response


@router.post(
    "/movimentos/{movimento_id}/rendimento", response_class=HTMLResponse
)
async def resolver_movimento_rendimento(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: uuid.UUID = Form(...),
    ativo_id: uuid.UUID | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    resolvido = await resolver_como_rendimento(
        session,
        linha_id=movimento_id,
        categoria_id=categoria_id,
        ativo_id=ativo_id,
    )
    if not resolvido:
        raise HTTPException(
            status_code=404, detail="movimento não encontrado ou já resolvido"
        )
    return templates.TemplateResponse(request, "movimento_linha_resolvido.html", {})


@router.post(
    "/movimentos/{movimento_id}/transferencia_manual",
    response_class=HTMLResponse,
)
async def resolver_movimento_transferencia_manual(
    movimento_id: uuid.UUID,
    request: Request,
    conta_relacionada_id: uuid.UUID = Form(...),
    session: AsyncSession = Depends(get_session),
):
    resolvido = await resolver_como_transferencia(
        session,
        linha_id=movimento_id,
        conta_relacionada_id=conta_relacionada_id,
    )
    if not resolvido:
        raise HTTPException(
            status_code=404, detail="movimento não encontrado ou já resolvido"
        )
    return templates.TemplateResponse(request, "movimento_linha_resolvido.html", {})


@router.post(
    "/movimentos/{movimento_id}/ignorar", response_class=HTMLResponse
)
async def resolver_movimento_ignorar(
    movimento_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    resolvido = await ignorar_linha(session, linha_id=movimento_id)
    if not resolvido:
        raise HTTPException(
            status_code=404, detail="movimento não encontrado ou já resolvido"
        )
    return templates.TemplateResponse(request, "movimento_linha_resolvido.html", {})


@router.post(
    "/movimentos/{movimento_id}/transferencia", response_class=HTMLResponse
)
async def categorizar_movimento_transferencia(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: uuid.UUID = Form(...),
    session: AsyncSession = Depends(get_session),
):
    categorizado = await categorizar_transferencia(
        session, movimento_id=movimento_id, categoria_id=categoria_id
    )
    if not categorizado:
        raise HTTPException(
            status_code=404,
            detail="transferência não encontrada ou já categorizada",
        )
    return templates.TemplateResponse(request, "movimento_linha_resolvido.html", {})


@router.get("/titulares/novo")
async def form_titular_novo(
    request: Request, session: AsyncSession = Depends(get_session)
):
    return templates.TemplateResponse(
        request, "titular_novo.html", {"total_alertas": await _contar_alertas(session)}
    )


@router.post("/titulares/novo")
async def criar_titular_novo(
    nome: str = Form(...),
    tipo: str = Form(...),
    data_nascimento: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    await titular_repo.criar_titular(
        session,
        nome=nome,
        tipo=tipo,
        data_nascimento=date.fromisoformat(data_nascimento)
        if data_nascimento
        else None,
    )
    await session.commit()
    return RedirectResponse(url="/titulares/novo", status_code=303)


@router.get("/rendimentos-recorrentes/novo")
async def form_rendimento_recorrente_novo(
    request: Request, session: AsyncSession = Depends(get_session)
):
    titulares = await titular_repo.listar_titulares(session)
    contas = await conta_repo.listar_todas_ativas(session)
    categorias_despesa = await categoria_repo.listar_grupos_com_categorias(
        session, tipo="despesa"
    )
    categorias_receita = await categoria_repo.listar_grupos_com_categorias(
        session, tipo="receita"
    )
    return templates.TemplateResponse(
        request,
        "rendimento_recorrente_novo.html",
        {
            "titulares": titulares,
            "contas": contas,
            "categorias_despesa": categorias_despesa,
            "categorias_receita": categorias_receita,
            "total_alertas": await _contar_alertas(session),
        },
    )


@router.post("/rendimentos-recorrentes/novo")
async def criar_rendimento_recorrente_novo(
    titular_id: str = Form(...),
    conta_id: str = Form(""),
    tipo: str = Form(...),
    categoria_id: str = Form(...),
    valor: str = Form(...),
    dia_do_mes: int = Form(...),
    descricao: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    await recorrente_repo.criar_recorrente(
        session,
        tipo=tipo,
        categoria_id=uuid.UUID(categoria_id),
        titular_id=uuid.UUID(titular_id),
        conta_id=uuid.UUID(conta_id) if conta_id else None,
        valor=Decimal(valor),
        dia_do_mes=dia_do_mes,
        descricao=descricao,
    )
    await session.commit()
    return RedirectResponse(
        url="/rendimentos-recorrentes/novo", status_code=303
    )


@router.post(
    "/movimentos/manual/{movimento_id}/categorizar",
    response_class=HTMLResponse,
)
async def categorizar_movimento_manual(
    movimento_id: uuid.UUID,
    request: Request,
    categoria_id: uuid.UUID = Form(...),
    conta_id: uuid.UUID = Form(...),
    ativo_id: uuid.UUID | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    movimento = await session.get(Movimento, movimento_id)
    if (
        movimento is None
        or movimento.origem not in movimento_repo.ORIGENS_CATEGORIZAVEIS
    ):
        raise HTTPException(status_code=404, detail="movimento não encontrado")

    if movimento.conta_id is None:
        movimento.conta_id = conta_id
    resultado = await session.execute(
        select(MovimentoLinha).where(MovimentoLinha.movimento_id == movimento_id)
    )
    for linha in resultado.scalars().all():
        linha.categoria_id = categoria_id
        linha.ativo_id = ativo_id

    await session.commit()
    return templates.TemplateResponse(
        request, "movimento_linha_resolvido.html", {}
    )


@router.post("/registo-rapido")
async def registo_rapido(
    request: Request,
    texto: str = Form(...),
    tipo: str = Form(...),
    categoria_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    titulares = await titular_repo.listar_titulares(session)
    if not titulares:
        return RedirectResponse(
            url="/?msg=Nenhum titular encontrado.", status_code=303
        )

    tipo_movimento = {"despesa": "saida", "rendimento": "entrada"}.get(tipo)
    if tipo_movimento is None:
        return RedirectResponse(url="/?msg=Tipo inválido.", status_code=303)

    mensagem = await registar_movimento_rapido(
        session,
        titular=titulares[0],
        texto=texto,
        tipo=tipo_movimento,
        ambito="pessoal",
        categoria_id=uuid.UUID(categoria_id) if categoria_id else None,
    )
    return RedirectResponse(url=f"/?msg={quote(mensagem)}", status_code=303)


@router.get("/registo")
async def registo_form(
    request: Request,
    conta_id: str = "",
    tipo: str = "",
    session: AsyncSession = Depends(get_session),
):
    grupos_todos = (
        await categoria_repo.listar_todos_os_grupos_com_categorias(session)
    )
    contas = await conta_repo.listar_todas_ativas(session)

    grupos = [
        (
            grupo,
            [c for c in categorias if c.nome in CATEGORIAS_CARTAO_REFEICAO],
        )
        for grupo, categorias in grupos_todos
    ]
    grupos = [(grupo, categorias) for grupo, categorias in grupos if categorias]
    contas_filtradas = [c for c in contas if c.tipo == "cartao_refeicao"]

    return templates.TemplateResponse(
        request,
        "registo.html",
        {
            "grupos": grupos,
            "contas": contas_filtradas,
            "selected_conta": conta_id,
            "selected_tipo": tipo,
            "hoje": date.today().isoformat(),
        },
    )


@router.post("/registo")
async def registo_post(
    request: Request,
    tipo: str = Form(...),
    valor: str = Form(...),
    descricao: str = Form(""),
    categoria_id: str = Form(""),
    data: str = Form(""),
    conta_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    titulares = await titular_repo.listar_titulares(session)
    if not titulares:
        return RedirectResponse(
            url="/registo?msg=Nenhum titular encontrado.", status_code=303
        )
    titular = titulares[0]

    try:
        valor_dec = parse_valor_pt(valor)
    except InvalidOperation:
        return RedirectResponse(
            url="/registo?msg=Valor inválido.", status_code=303
        )
    if valor_dec <= 0:
        return RedirectResponse(
            url="/registo?msg=Valor inválido (tem de ser maior que 0).",
            status_code=303,
        )

    if data.strip():
        try:
            data_mov = date.fromisoformat(data.strip())
        except ValueError:
            return RedirectResponse(
                url="/registo?msg=Data inválida.", status_code=303
            )
    else:
        data_mov = date.today()
    if data_mov > date.today():
        return RedirectResponse(
            url="/registo?msg=A data não pode ser futura.", status_code=303
        )

    if not descricao:
        descricao = (
            "Despesa avulsa" if tipo == "despesa" else "Rendimento avulso"
        )
    tipo_mov = "saida" if tipo == "despesa" else "entrada"

    contas = [
        c
        for c in await conta_repo.listar_todas_ativas(session)
        if c.tipo == "cartao_refeicao"
    ]
    if not conta_id.strip():
        return RedirectResponse(
            url="/registo?msg=Escolhe o cartão de refeição.", status_code=303
        )
    try:
        conta_escolhida_id = uuid.UUID(conta_id.strip())
    except ValueError:
        return RedirectResponse(
            url="/registo?msg=Conta inválida.", status_code=303
        )
    conta_escolhida = next(
        (c for c in contas if c.id == conta_escolhida_id), None
    )
    if conta_escolhida is None:
        return RedirectResponse(
            url="/registo?msg=Conta inválida.", status_code=303
        )
    conta_final_id = conta_escolhida.id

    await movimento_repo.criar_movimento(
        session,
        tipo=tipo_mov,
        valor=valor_dec,
        data=data_mov,
        origem="manual",
        descricao=descricao,
        titular_id=titular.id,
        registado_por=titular.id,
        ambito="pessoal",
        conta_id=conta_final_id,
        linhas=[
            movimento_repo.LinhaNova(
                valor=valor_dec,
                categoria_id=uuid.UUID(categoria_id) if categoria_id else None,
                descricao=descricao,
            )
        ],
    )
    await session.commit()

    return RedirectResponse(
        url=f"/registo?msg=Registado com sucesso: {descricao} - {valor_dec}€",
        status_code=303,
    )
