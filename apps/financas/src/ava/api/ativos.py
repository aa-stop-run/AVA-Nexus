import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import _contar_alertas, templates
from ava.db import get_session
from ava.financas import valorizacao
from ava.financas.saldos import TIPOS_PASSIVO
from ava.models.categoria import Categoria
from ava.models.conta import Conta
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.repositories import (
    ativo_repo,
    ativo_valor_repo,
    conta_repo,
    contrato_repo,
    saldo_historico_repo,
    titular_repo,
)

router = APIRouter(tags=["ativos"])

# Limites aceites para ativo.taxa_anual (fração). -0.99 (-99%) evita uma base <= 0 na potência
# composta de valorizacao.projetar — a partir de -100% a base fica não positiva e InvalidOperation
# rebenta em TODAS as páginas que leem o valor do bem: /, /patrimonio, /configuracoes/patrimonio
# e a própria página do ativo, que é o único sítio com o formulário para a corrigir. 9.99 (+999%)
# fica dentro do que Numeric(5,4) representa sem "numeric field overflow" no commit.
TAXA_ANUAL_MIN = Decimal("-0.99")
TAXA_ANUAL_MAX = Decimal("9.99")


@router.get("/patrimonio/ativos/{ativo_id}", response_class=HTMLResponse)
async def ativo_detalhe(
    ativo_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    ativo = await ativo_repo.obter_por_id(session, ativo_id)
    if not ativo:
        raise HTTPException(status_code=404, detail="Ativo não encontrado")

    stmt = (
        select(MovimentoLinha, Movimento)
        .join(Movimento)
        .where(MovimentoLinha.ativo_id == ativo_id)
        .where(MovimentoLinha.leitura_odometro.isnot(None))
        # Hoje inalcançável (leitura_odometro só é escrito a partir de resolver_como_despesa,
        # sempre "saida"), mas mantém esta consulta simétrica com a de despesas, 70 linhas
        # abaixo, que já filtra por tipo — evita que o próximo leitor leia a ausência como esquecimento.
        .where(Movimento.tipo == "saida")
        .order_by(Movimento.data.asc(), MovimentoLinha.leitura_odometro.asc())
    )
    result = await session.execute(stmt)
    linhas = result.all()

    abastecimentos = []
    total_litros = Decimal(0)
    total_custo = Decimal(0)
    primeiro_odometro = None
    ultimo_odometro = None

    for i, (linha, movimento) in enumerate(linhas):
        odometro = linha.leitura_odometro
        litros = linha.quantidade or Decimal(0)
        custo = linha.valor

        l_100km = None
        c_100km = None
        if i > 0 and litros > 0:
            odometro_anterior = linhas[i - 1][0].leitura_odometro
            distancia = odometro - odometro_anterior
            if distancia > 0:
                l_100km = (litros / Decimal(distancia)) * 100
                c_100km = (custo / Decimal(distancia)) * 100

        abastecimentos.append(
            {
                "data": movimento.data,
                "odometro": odometro,
                "litros": litros,
                "custo": custo,
                "l_100km": l_100km,
                "c_100km": c_100km,
            }
        )

        if primeiro_odometro is None:
            primeiro_odometro = odometro
        ultimo_odometro = odometro

        if i > 0:
            total_litros += litros
            total_custo += custo

    media_global_l_100km = None
    media_global_c_100km = None
    distancia_total = 0
    if primeiro_odometro and ultimo_odometro and ultimo_odometro > primeiro_odometro:
        distancia_total = ultimo_odometro - primeiro_odometro
        media_global_l_100km = (total_litros / Decimal(distancia_total)) * 100
        media_global_c_100km = (total_custo / Decimal(distancia_total)) * 100

    # total_custo, calculado no loop acima, exclui de propósito o primeiro abastecimento (não há
    # distância anterior para lhe associar um consumo médio). Para o TOTAL gasto em combustível
    # esse abastecimento conta na mesma — daí somar de volta o valor da primeira linha.
    total_custo_abastecimentos = (
        total_custo + (linhas[0][0].valor if linhas else Decimal(0))
    )

    # Segunda consulta, sem o filtro de leitura_odometro: TODAS as despesas ligadas a este ativo
    # (seguro, IUC, reparações, ... — não só combustível), com a categoria à mistura para o
    # agrupamento por categoria e para rotular cada despesa na tabela "Histórico de Custos".
    #
    # Além das despesas atribuídas diretamente a este bem, contam as que foram marcadas como
    # pertencendo a um crédito que financiou este bem — juros, imposto de selo, comissões (ver a
    # spec 2026-08-07, §4). É um OR no WHERE, não um join a mais: uma linha que satisfaça as duas
    # condições continua a aparecer UMA vez, sem dupla contagem.
    #
    # Só `saida`: o capital amortizado é uma `transferencia` e não é custo — o dinheiro não
    # desapareceu, mudou de sítio no balanço. O filtro exclui deliberadamente também as
    # `entrada` atribuídas a este bem — um rendimento (ex.: reembolso) marcado com este ativo_id
    # não é um custo, e sem este filtro entrava a somar no "Total Gasto".
    # Filtra por `tipo` (para nunca apanhar uma conta reclassificada para fora de dívida — ver
    # Achado 1 da revisão), mas DELIBERADAMENTE não por `ativo`: o custo de posse é história.
    # Os juros pagos por um crédito entretanto encerrado/apagado continuam a ser um custo de ter
    # tido o bem, e não podem desaparecer da página só porque a conta foi arquivada. O valor
    # líquido (acima) é o presente e filtra por `ativo`; o custo (abaixo) é o passado e não filtra.
    contas_do_bem = (
        select(Conta.id)
        .where(
            Conta.ativo_id == ativo_id,
            Conta.tipo.in_(TIPOS_PASSIVO),
        )
        .scalar_subquery()
    )
    stmt_despesas = (
        select(MovimentoLinha, Movimento, Categoria)
        .join(Movimento, MovimentoLinha.movimento_id == Movimento.id)
        .outerjoin(Categoria, MovimentoLinha.categoria_id == Categoria.id)
        .where(
            Movimento.tipo == "saida",
            or_(
                MovimentoLinha.ativo_id == ativo_id,
                MovimentoLinha.conta_relacionada_id.in_(contas_do_bem),
            ),
        )
        .order_by(Movimento.data.desc())
    )
    result_despesas = await session.execute(stmt_despesas)
    despesas_linhas = result_despesas.all()

    total_gasto_geral = Decimal("0")
    # dict simples em vez de group by SQL: o nome da categoria já vem resolvido (outerjoin), e o
    # volume de linhas por ativo é sempre pequeno o suficiente para agregar em Python sem custo.
    custos_por_categoria: dict[str, Decimal] = {}
    outras_despesas = []

    for linha, movimento, categoria in despesas_linhas:
        total_gasto_geral += linha.valor
        nome_categoria = (
            categoria.nome if categoria is not None else "Sem categoria"
        )
        custos_por_categoria[nome_categoria] = (
            custos_por_categoria.get(nome_categoria, Decimal("0")) + linha.valor
        )
        # "Outras despesas" são as que não são abastecimento (sem leitura_odometro) — os
        # abastecimentos já têm a própria secção "Histórico de Fuel Logs".
        if linha.leitura_odometro is None:
            outras_despesas.append(
                {
                    "data": movimento.data,
                    "descricao": movimento.descricao,
                    "categoria": nome_categoria,
                    "valor": linha.valor,
                }
            )

    gastos_por_categoria = sorted(
        custos_por_categoria.items(), key=lambda item: item[1], reverse=True
    )

    avaliacao_atual = await ativo_repo.valor_atual(session, ativo)
    historico_valor = await ativo_valor_repo.listar_por_ativo(session, ativo_id)

    # Dívidas ligadas a este bem e valor líquido. APRESENTAÇÃO apenas: as fórmulas de
    # patrimonio_financeiro e patrimonio_total não mudam — a dívida já está subtraída lá, e
    # subtraí-la outra vez contaria a hipoteca em dobro (ver a spec 2026-08-07, §3.1).
    dividas_do_bem = []
    total_em_divida = Decimal("0")
    for conta_divida in await conta_repo.listar_dividas_do_ativo(
        session, ativo_id
    ):
        # DERIVADO, como /patrimonio (ver ali) — a âncora crua fica desatualizada assim que uma
        # amortização é registada e o extrato seguinte ainda não chegou, e as duas páginas
        # mostrarem valores diferentes do MESMO bem é exatamente o que a revisão final apanhou
        # (achado 5).
        derivado = await saldo_historico_repo.saldo_derivado(
            session, conta_divida
        )
        em_divida = derivado.valor if derivado is not None else Decimal("0")
        dividas_do_bem.append({"conta": conta_divida, "em_divida": em_divida})
        total_em_divida += em_divida

    contratos_do_bem = await contrato_repo.listar_por_ativo(
        session, ativo_id, apenas_ativos=True
    )

    valor_liquido = (
        avaliacao_atual.valor - total_em_divida if avaliacao_atual is not None else None
    )

    return templates.TemplateResponse(
        request,
        "ativo_detalhe.html",
        {
            "ativo": ativo,
            "abastecimentos": list(reversed(abastecimentos)),
            "media_global_l_100km": media_global_l_100km,
            "media_global_c_100km": media_global_c_100km,
            "total_gasto_geral": total_gasto_geral,
            "total_custo_abastecimentos": total_custo_abastecimentos,
            "gastos_por_categoria": gastos_por_categoria,
            "outras_despesas": outras_despesas,
            "avaliacao_atual": avaliacao_atual,
            "historico_valor": historico_valor,
            "taxa_omissao": valorizacao.taxa_de(ativo.tipo, None),
            "hoje_iso": date.today().isoformat(),
            "dividas_do_bem": dividas_do_bem,
            "total_em_divida": total_em_divida,
            "valor_liquido": valor_liquido,
            "contratos_do_bem": contratos_do_bem,
            "tipo_labels": contrato_repo.TIPO_LABELS,
            "hoje": date.today(),
        },
    )


@router.post("/patrimonio/ativos/{ativo_id}/avaliacao")
async def registar_avaliacao_ativo(
    ativo_id: uuid.UUID,
    data: str = Form(...),
    valor: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Regista uma avaliação OBSERVADA. Mesma data que uma existente → substitui-a.

    Um valor ou data malformados são ignorados em silêncio (redirect sem gravar), pelo mesmo
    princípio de _parse_filtros_movimentos: um erro de digitação não deve devolver um 422 cru.
    Uma data futura leva o mesmo tratamento: "observado" só faz sentido para algo que já
    aconteceu, e um erro de dedo (ex.: 2062 em vez de 2026) meteria um ponto no futuro que
    passaria a dominar o KPI de património (serie[-1]) sem que `obter_valor_em_data(hoje)`
    alguma vez o mostrasse na página do ativo — o utilizador nunca perceberia a causa.
    """
    ativo = await ativo_repo.obter_por_id(session, ativo_id)
    if ativo is None:
        raise HTTPException(status_code=404, detail="ativo não encontrado")

    try:
        valor_decimal = Decimal(valor.strip().replace(",", "."))
        data_avaliacao = date.fromisoformat(data.strip())
    except (InvalidOperation, ValueError, AttributeError):
        return RedirectResponse(url=f"/patrimonio/ativos/{ativo_id}", status_code=303)

    if valor_decimal <= 0 or data_avaliacao > date.today():
        return RedirectResponse(url=f"/patrimonio/ativos/{ativo_id}", status_code=303)

    await ativo_valor_repo.registar_valor(
        session, ativo_id=ativo_id, data=data_avaliacao, valor=valor_decimal
    )
    await session.commit()
    return RedirectResponse(url=f"/patrimonio/ativos/{ativo_id}", status_code=303)


@router.post("/patrimonio/ativos/{ativo_id}/avaliacao/{avaliacao_id}/apagar")
async def apagar_avaliacao_ativo(
    ativo_id: uuid.UUID,
    avaliacao_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Apaga uma avaliação — um facto observado, por isso confirma primeiro que `avaliacao_id`
    pertence de facto a `ativo_id`. Sem esta verificação, o URL de qualquer avaliação apagaria
    a avaliação de QUALQUER ativo, bastando trocar o `ativo_id` no caminho.
    """
    avaliacao = await ativo_valor_repo.obter_por_id(session, avaliacao_id)
    if avaliacao is None or avaliacao.ativo_id != ativo_id:
        raise HTTPException(status_code=404, detail="avaliação não encontrada")

    await ativo_valor_repo.apagar(session, avaliacao_id)
    await session.commit()
    return RedirectResponse(url=f"/patrimonio/ativos/{ativo_id}", status_code=303)


@router.post("/patrimonio/ativos/{ativo_id}/taxa")
async def definir_taxa_ativo(
    ativo_id: uuid.UUID,
    taxa_anual: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    """Define a taxa de variação anual própria deste bem. Vazio → volta à omissão do tipo.

    O formulário fala em percentagem (-15) porque é assim que uma pessoa pensa; a coluna guarda
    a fração (-0.15), que é o que a matemática usa.
    """
    ativo = await ativo_repo.obter_por_id(session, ativo_id)
    if ativo is None:
        raise HTTPException(status_code=404, detail="ativo não encontrado")

    if not taxa_anual.strip():
        ativo.taxa_anual = None
    else:
        try:
            taxa_decimal = Decimal(taxa_anual.strip().replace(",", ".")) / Decimal("100")
        except InvalidOperation:
            pass  # digitação inválida ignorada, como nos restantes formulários
        else:
            # Fora do intervalo aceite é ignorado em silêncio, pelo mesmo motivo que uma
            # digitação inválida: gravar trancaria as páginas listadas acima sem saída pelo UI.
            if TAXA_ANUAL_MIN <= taxa_decimal <= TAXA_ANUAL_MAX:
                ativo.taxa_anual = taxa_decimal

    await session.commit()
    return RedirectResponse(url=f"/patrimonio/ativos/{ativo_id}", status_code=303)


@router.get("/ativos/novo")
async def form_ativo_novo(request: Request, session: AsyncSession = Depends(get_session)):
    titulares = await titular_repo.listar_titulares(session)
    return templates.TemplateResponse(
        request,
        "ativo_novo.html",
        {"titulares": titulares, "total_alertas": await _contar_alertas(session)},
    )


@router.post("/ativos/novo")
async def criar_ativo_novo(
    titular_id: str = Form(...),
    nome: str = Form(...),
    tipo: str = Form(...),
    valor_atual: str = Form(""),
    data_aquisicao: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    data = date.fromisoformat(data_aquisicao) if data_aquisicao else None
    ativo = await ativo_repo.criar_ativo(
        session,
        titular_id=uuid.UUID(titular_id),
        nome=nome,
        tipo=tipo,
        data_aquisicao=data,
    )

    # O valor introduzido no formulário é o preço de compra: vira a primeira observação, datada
    # da aquisição. É a única observação que se pode datar do passado com confiança — uma
    # data_aquisicao futura não pode gerar uma avaliação datada no futuro (mesmo defeito do
    # ponto 2 em registar_avaliacao_ativo/configuracoes_ativos_post: corromperia o KPI de
    # património e a série do gráfico da home). Tratada como entrada malformada: ignorada em
    # silêncio, sem gravar avaliação — o ativo continua a ser criado.
    if valor_atual.strip():
        try:
            valor_decimal = Decimal(valor_atual.strip().replace(",", "."))
        except InvalidOperation:
            valor_decimal = Decimal("0")
        data_avaliacao = data or date.today()
        if valor_decimal > 0 and data_avaliacao <= date.today():
            await ativo_valor_repo.registar_valor(
                session,
                ativo_id=ativo.id,
                data=data_avaliacao,
                valor=valor_decimal,
                origem="aquisicao",
            )

    await session.commit()
    return RedirectResponse(url="/patrimonio", status_code=303)
