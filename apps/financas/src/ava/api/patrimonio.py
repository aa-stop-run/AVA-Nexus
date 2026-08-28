import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import (
    CATEGORIA_DIVIDA_LABELS,
    CATEGORIA_INVESTIMENTO_LABELS,
    _contar_alertas,
    _parse_filtros_movimentos,
    templates,
)
from ava.db import get_session
from ava.financas.saldos import TIPOS_PASSIVO
from ava.models.ressarcimento import Ressarcimento
from ava.repositories import (
    ativo_repo,
    conta_repo,
    movimento_repo,
    ressarcimento_repo,
    saldo_historico_repo,
    titular_repo,
)

router = APIRouter(tags=["patrimonio"])


@router.get("/patrimonio")
async def patrimonio(request: Request, session: AsyncSession = Depends(get_session)):
    serie_patrimonio = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(session)
    contas = await conta_repo.listar_todas_ativas(session)

    investimentos_por_categoria: dict[str, list[dict]] = {}
    contas_simples: list[dict] = []  # à ordem, poupança, certificados, cartão refeição
    dividas_por_categoria: dict[str, list[dict]] = {}
    total_ativos = Decimal("0")
    total_dividas = Decimal("0")

    for conta in contas:
        # O saldo mostrado é o DERIVADO: âncora + movimentos desde ela (spec §12). A fórmula de
        # patrimonio_financeiro/patrimonio_total não muda — muda a origem do `valor` de cada
        # conta.
        derivado = await saldo_historico_repo.saldo_derivado(session, conta)
        valor = derivado.valor if derivado else Decimal("0")
        linha = {
            "conta": conta,
            "saldo": valor,
            # None quando a conta não tem âncora nenhuma: o template mostra "—" e não 0,00 €,
            # porque uma soma de movimentos sem ponto de partida não é um saldo (§3.2).
            "derivado": derivado,
        }

        if conta.tipo in TIPOS_PASSIVO:
            total_dividas += valor
            categoria = conta.categoria_divida or "outro"
            dividas_por_categoria.setdefault(categoria, []).append(linha)
        elif conta.tipo == "investimento":
            total_ativos += valor
            categoria = conta.categoria_investimento or "outro"
            investimentos_por_categoria.setdefault(categoria, []).append(linha)
        else:
            total_ativos += valor
            contas_simples.append(linha)

    investimentos = [
        {
            "categoria": CATEGORIA_INVESTIMENTO_LABELS.get(chave, chave),
            "linhas": investimentos_por_categoria[chave],
        }
        for chave in CATEGORIA_INVESTIMENTO_LABELS
        if chave in investimentos_por_categoria
    ]
    creditos = [
        {
            "categoria": CATEGORIA_DIVIDA_LABELS.get(chave, chave),
            "linhas": dividas_por_categoria[chave],
        }
        for chave in CATEGORIA_DIVIDA_LABELS
        if chave in dividas_por_categoria
    ]

    # `total_ativos` fica com o património FINANCEIRO (só saldos reais). Os bens entram
    # separadamente, para uma estimativa de valor de carro nunca contaminar o número exato.
    patrimonio_financeiro = total_ativos - total_dividas

    ativos_fisicos = []
    total_bens = Decimal("0")
    for ativo in await ativo_repo.listar_todos_ativos(session):
        avaliacao = await ativo_repo.valor_atual(session, ativo)
        ativos_fisicos.append(
            {
                "ativo": ativo,
                "valor": avaliacao.valor if avaliacao else None,
                "e_projetado": avaliacao.e_projetado if avaliacao else False,
                "data_observacao": avaliacao.data_observacao if avaliacao else None,
            }
        )
        if avaliacao is not None:
            total_bens += avaliacao.valor

    return templates.TemplateResponse(
        request,
        "patrimonio.html",
        {
            "contas_simples": contas_simples,
            "investimentos": investimentos,
            "creditos": creditos,
            "ativos_fisicos": ativos_fisicos,
            "total_ativos": total_ativos,
            "total_dividas": total_dividas,
            "patrimonio_financeiro": patrimonio_financeiro,
            "patrimonio_total": patrimonio_financeiro + total_bens,
            "total_bens": total_bens,
            "serie_patrimonio": [
                {
                    "data": d.isoformat(),
                    # float(...) aqui é serialização para o JSON do gráfico, não aritmética —
                    # nenhuma soma acontece depois desta linha. A aritmética toda já aconteceu em
                    # Decimal dentro de listar_patrimonio_liquido_no_tempo.
                    "financeiro": float(f),
                    "total": float(t),
                    # Só o último ponto é estimado. O gráfico desenha esse segmento tracejado,
                    # para não dar a um número calculado o mesmo peso visual de um que o banco
                    # confirmou.
                    "e_estimado": e_estimado,
                }
                for d, f, t, e_estimado in serie_patrimonio
            ],
            "total_alertas": await _contar_alertas(session),
        },
    )


@router.get("/patrimonio/contas/{conta_id}")
async def patrimonio_conta_movimentos(
    conta_id: uuid.UUID,
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
    conta = await conta_repo.obter_por_id(session, conta_id)
    if conta is None:
        raise HTTPException(status_code=404, detail="conta não encontrada")

    # Default to current month if no filters are provided
    if mes_ano is None and not any(
        [busca, valor_min, valor_max, data_inicio, data_fim, tipo_movimento]
    ):
        mes_ano = date.today().strftime("%Y-%m")

    filtros = _parse_filtros_movimentos(
        busca=busca,
        valor_min=valor_min,
        valor_max=valor_max,
        data_inicio=data_inicio,
        data_fim=data_fim,
        mes_ano=mes_ano,
        tipo_movimento=tipo_movimento,
    )
    movimentos_brutos = await movimento_repo.listar_por_conta(session, conta_id, **filtros)
    ativos_disponiveis = await ativo_repo.listar_todos_ativos(session)
    creditos_disponiveis = await conta_repo.listar_dividas_ativas(session)
    ressarcimentos_disponiveis = await ressarcimento_repo.listar_recentes(session)

    # Mesmo saldo DERIVADO que /patrimonio mostra (ver ali) — None quando a conta não tem
    # nenhuma âncora, e o template mostra "—" em vez de 0,00 €.
    derivado = await saldo_historico_repo.saldo_derivado(session, conta)

    # Uma transferência (ver reconciliacao.conciliar_amortizacoes_de_credito) tem DUAS contas
    # envolvidas — mostra o nome da OUTRA conta (não esta), para ficar claro de/para onde o
    # dinheiro foi, independentemente de se está a ver o lado de origem ou de destino.
    linhas = []
    grupos_antigos_a_incluir: set[uuid.UUID] = set()

    for movimento in movimentos_brutos:
        outra_conta_nome = None
        if movimento.tipo == "transferencia":
            outro_id = (
                movimento.conta_destino_id
                if movimento.conta_id == conta_id
                else movimento.conta_id
            )
            outra_conta = (
                await conta_repo.obter_por_id(session, outro_id) if outro_id else None
            )
            outra_conta_nome = outra_conta.nome if outra_conta is not None else None

        ressarcimento_id_atual = (
            movimento.linhas[0].ressarcimento_id if movimento.linhas else None
        )
        if ressarcimento_id_atual is not None:
            # Marca este grupo para verificação (se não estiver em listar_recentes, será incluído)
            grupos_antigos_a_incluir.add(ressarcimento_id_atual)

        linhas.append(
            {
                "movimento": movimento,
                "outra_conta_nome": outra_conta_nome,
                "e_destino": movimento.conta_destino_id == conta_id,
                "ativo_id_atual": movimento.linhas[0].ativo_id if movimento.linhas else None,
                "conta_relacionada_id_atual": (
                    movimento.linhas[0].conta_relacionada_id if movimento.linhas else None
                ),
                "ressarcimento_id_atual": ressarcimento_id_atual,
            }
        )

    # Se algum grupo ligado a um movimento não está em listar_recentes (porque é mais antigo),
    # busca-o e antepõe à lista para que fique selected no dropdown.
    ids_na_lista = {grupo.id for grupo, _ in ressarcimentos_disponiveis}
    for grupo_id in grupos_antigos_a_incluir:
        if grupo_id not in ids_na_lista:
            grupo_atual = await session.get(Ressarcimento, grupo_id)
            if grupo_atual is not None:
                resumo_atual = await ressarcimento_repo.resumo(session, grupo_id)
                ressarcimentos_disponiveis = [
                    (grupo_atual, resumo_atual)
                ] + ressarcimentos_disponiveis
                ids_na_lista.add(grupo_id)

    return templates.TemplateResponse(
        request,
        "conta_movimentos.html",
        {
            "conta": conta,
            "movimentos": linhas,
            "derivado": derivado,
            "filtros_form": {
                "busca": busca or "",
                "valor_min": valor_min or "",
                "valor_max": valor_max or "",
                "data_inicio": data_inicio or "",
                "data_fim": data_fim or "",
                "mes_ano": mes_ano or "",
                "tipo_movimento": tipo_movimento or "",
            },
            "ativos_disponiveis": ativos_disponiveis,
            "creditos_disponiveis": creditos_disponiveis,
            "ressarcimentos_disponiveis": ressarcimentos_disponiveis,
            "total_alertas": await _contar_alertas(session),
        },
    )


@router.get("/contas/novo")
async def form_conta_novo(request: Request, session: AsyncSession = Depends(get_session)):
    titulares = await titular_repo.listar_titulares(session)
    return templates.TemplateResponse(
        request,
        "conta_novo.html",
        {"titulares": titulares, "total_alertas": await _contar_alertas(session)},
    )


@router.post("/contas/novo")
async def criar_conta_novo(
    titular_id: str = Form(...),
    instituicao: str = Form(...),
    tipo: str = Form(...),
    nome: str = Form(...),
    categoria_divida: str = Form(""),
    categoria_investimento: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    await conta_repo.criar_conta(
        session,
        titular_id=uuid.UUID(titular_id),
        instituicao=instituicao,
        tipo=tipo,
        nome=nome,
        categoria_divida=categoria_divida if categoria_divida else None,
        categoria_investimento=categoria_investimento if categoria_investimento else None,
    )
    await session.commit()
    return RedirectResponse(url="/contas/novo", status_code=303)
