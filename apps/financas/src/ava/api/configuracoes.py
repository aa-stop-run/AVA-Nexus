import uuid

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.dashboard import _contar_alertas
from ava.db import get_session
from ava.financas.natureza import natureza_valida, naturezas_de
from ava.financas.saldos import TIPOS_PASSIVO, parse_valor_pt
from ava.repositories import (
    ativo_repo,
    ativo_valor_repo,
    categoria_repo,
    conta_repo,
    saldo_historico_repo,
    titular_repo,
)

router = APIRouter(tags=["configuracoes"])
templates = Jinja2Templates(directory="src/ava/templates")

def format_pt(value):
    if value is None:
        return ""
    return "{:,.2f}".format(float(value)).replace(",", "X").replace(".", ",").replace("X", ".")
templates.env.filters["format_pt"] = format_pt


# grupo_categoria.nome e categoria.nome são String(60) — ver ava.models.grupo_categoria e
# ava.models.categoria. Validado aqui para dar um erro amigável em vez de deixar rebentar como
# DataError não tratado (500) quando o nome excede o limite da coluna.
_NOME_MAX_LEN = 60

# Rótulos das naturezas para a interface. O valor guardado é sem acentos (ver a constraint
# ck_categoria_natureza); o que se mostra ao utilizador não tem de ser.
ETIQUETAS_NATUREZA = {
    "recorrente": "Recorrente",
    "extraordinario": "Extraordinário",
    "fixa": "Fixa",
    "variavel": "Variável",
    "poupanca": "Poupança",
}


async def _pagina(request: Request, session: AsyncSession, *, erro: str | None = None, status_code: int = 200):
    grupos = await categoria_repo.listar_todos_os_grupos_com_categorias(session)
    return templates.TemplateResponse(
        request,
        "configuracoes_categorias.html",
        {
            "grupos": grupos,
            "erro": erro,
            "etiquetas_natureza": ETIQUETAS_NATUREZA,
            "naturezas_de": naturezas_de,
            "total_alertas": await _contar_alertas(session),
        },
        status_code=status_code,
    )


@router.get("/configuracoes", response_class=RedirectResponse)
async def configuracoes_redirect():
    return RedirectResponse(url="/configuracoes/categorias", status_code=303)

from ava.repositories import orcamento_repo
from decimal import Decimal

@router.get("/configuracoes/orcamentos", response_class=HTMLResponse)
async def configuracoes_orcamentos(
    request: Request, 
    erro: str | None = None,
    session: AsyncSession = Depends(get_session)
):
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    
    grupos = await categoria_repo.listar_todos_os_grupos_com_categorias(session)
    orcamentos = await orcamento_repo.listar_orcamentos(session, ano, mes)
    
    # Map by grupo_id
    orcamento_map = {o.grupo_categoria_id: o for o in orcamentos}
    
    orcamentos_info = []
    for g, _ in grupos:
        orcamentos_info.append({
            "grupo": g,
            "orcamento": orcamento_map.get(g.id)
        })
        
    return templates.TemplateResponse(
        request,
        "configuracoes_orcamentos.html",
        {
            "orcamentos_info": orcamentos_info, 
            "ano": ano, 
            "mes": mes,
            "erro": erro,
            "total_alertas": await _contar_alertas(session)
        },
    )

@router.post("/configuracoes/orcamentos", response_class=HTMLResponse)
async def atualizar_orcamentos_route(
    request: Request,
    grupo_id: uuid.UUID = Form(...),
    ano: int = Form(...),
    mes: int = Form(...),
    limite_mensal: Decimal = Form(...),
    session: AsyncSession = Depends(get_session)
):
    # Match EXATO deste mês: listar_orcamentos faria fallback para o orçamento vigente de outro
    # mês, e gravar setembro passaria a sobrescrever março (ver obter_por_grupo_e_mes).
    existente = await orcamento_repo.obter_por_grupo_e_mes(session, grupo_id, ano, mes)

    if existente:
        await orcamento_repo.atualizar_orcamento(session, existente.id, limite_mensal)
    else:
        await orcamento_repo.criar_orcamento(session, grupo_id, ano, mes, limite_mensal)
        
    return RedirectResponse(url="/configuracoes/orcamentos", status_code=303)


@router.get("/configuracoes/categorias", response_class=HTMLResponse)
async def configuracoes_categorias(request: Request, session: AsyncSession = Depends(get_session)):
    return await _pagina(request, session)


@router.post("/configuracoes/grupos", response_class=HTMLResponse)
async def criar_grupo_route(
    request: Request, nome: str = Form(...), session: AsyncSession = Depends(get_session)
):
    nome = nome.strip()
    grupos = await categoria_repo.listar_todos_os_grupos_com_categorias(session)

    if not nome:
        return await _pagina(request, session, erro="Nome do grupo: em branco.", status_code=422)
    if len(nome) > _NOME_MAX_LEN:
        return await _pagina(
            request, session, erro=f"Nome do grupo: máximo de {_NOME_MAX_LEN} carateres.", status_code=422
        )
    if any(grupo.nome == nome for grupo, _ in grupos):
        return await _pagina(
            request, session, erro=f'Já existe um grupo chamado "{nome}".', status_code=422
        )

    maior_ordem = max((grupo.ordem for grupo, _ in grupos), default=0)
    try:
        await categoria_repo.criar_grupo(session, nome=nome, ordem=maior_ordem + 1)
        await session.commit()
    except (IntegrityError, DataError):
        # Corrida entre dois pedidos quase simultâneos com o mesmo nome (duplo clique, dois
        # separadores): a pré-verificação acima passou para ambos, mas a constraint única da BD
        # (grupo_categoria.nome) só deixa um vencer. Sem isto, o segundo pedido rebentava com um
        # 500 em vez de mostrar o mesmo erro amigável que a pré-verificação já dá no caso comum.
        await session.rollback()
        return await _pagina(
            request, session, erro=f'Já existe um grupo chamado "{nome}".', status_code=422
        )
    return RedirectResponse(url="/configuracoes/categorias", status_code=303)


@router.post("/configuracoes/categorias", response_class=HTMLResponse)
async def criar_categoria_route(
    request: Request,
    grupo_id: str = Form(...),
    nome: str = Form(...),
    tipo: str = Form(...),
    natureza: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    nome = nome.strip()

    try:
        grupo_uuid = uuid.UUID(grupo_id)
    except ValueError:
        return await _pagina(request, session, erro="Grupo: seleção inválida.", status_code=422)

    if not nome:
        return await _pagina(request, session, erro="Nome da categoria: em branco.", status_code=422)
    if len(nome) > _NOME_MAX_LEN:
        return await _pagina(
            request, session, erro=f"Nome da categoria: máximo de {_NOME_MAX_LEN} carateres.", status_code=422
        )
    if tipo not in ("despesa", "receita"):
        return await _pagina(request, session, erro="Tipo: seleção inválida.", status_code=422)
    if not natureza_valida(tipo=tipo, natureza=natureza):
        return await _pagina(
            request, session, erro="Natureza: não é válida para este tipo.", status_code=422
        )

    grupos = await categoria_repo.listar_todos_os_grupos_com_categorias(session)
    grupo_encontrado = next((g for g, _ in grupos if g.id == grupo_uuid), None)
    if grupo_encontrado is None:
        return await _pagina(request, session, erro="Grupo: seleção inválida.", status_code=422)

    categorias_do_grupo = next(categorias for g, categorias in grupos if g.id == grupo_uuid)
    erro_duplicado = f'O grupo "{grupo_encontrado.nome}" já tem uma categoria chamada "{nome}".'
    if any(categoria.nome == nome for categoria in categorias_do_grupo):
        return await _pagina(request, session, erro=erro_duplicado, status_code=422)

    try:
        await categoria_repo.criar_categoria(
            session, grupo_id=grupo_uuid, nome=nome, tipo=tipo, natureza=natureza
        )
        await session.commit()
    except (IntegrityError, DataError):
        # Mesma corrida descrita em criar_grupo_route, aqui para a constraint
        # uq_categoria_grupo_nome (grupo_id, nome).
        await session.rollback()
        return await _pagina(request, session, erro=erro_duplicado, status_code=422)
    return RedirectResponse(url="/configuracoes/categorias", status_code=303)


@router.post("/configuracoes/categorias/{categoria_id}/natureza", response_class=HTMLResponse)
async def definir_natureza_route(
    categoria_id: uuid.UUID,
    request: Request,
    natureza: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Marca uma categoria como recorrente/extraordinária (receita) ou fixa/variável/poupança
    (despesa). Devolve só a célula, para htmx trocar no sítio.

    Valida a natureza contra o tipo ANTES de gravar: a constraint ck_categoria_natureza é a rede,
    não a validação — deixar rebentar lá dava um 500 em vez de um 422 com explicação.
    """
    categoria = await categoria_repo.obter_por_id(session, categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    if not natureza_valida(tipo=categoria.tipo, natureza=natureza):
        return HTMLResponse(
            f"Natureza inválida para uma categoria de {categoria.tipo}.", status_code=422
        )

    await categoria_repo.definir_natureza(session, categoria_id, natureza=natureza)
    await session.commit()

    return templates.TemplateResponse(
        request,
        "_natureza_cell.html",
        {
            "categoria": categoria,
            "etiquetas_natureza": ETIQUETAS_NATUREZA,
            "naturezas_de": naturezas_de,
        },
    )


# --- Titulares ---

@router.get("/configuracoes/titulares", response_class=HTMLResponse)
async def configuracoes_titulares_get(request: Request, erro: str | None = None, session: AsyncSession = Depends(get_session)):
    titulares = await titular_repo.listar_titulares(session)
    return templates.TemplateResponse(
        request, "configuracoes_titulares.html",
        {"titulares": titulares, "erro": erro, "total_alertas": await _contar_alertas(session)}
    )

@router.post("/configuracoes/titulares", response_class=HTMLResponse)
async def configuracoes_titulares_post(
    request: Request,
    nome: str = Form(...),
    tipo: str = Form(...),
    data_nascimento: str = Form(""),
    session: AsyncSession = Depends(get_session)
):
    nome = nome.strip()
    if not nome:
        return await configuracoes_titulares_get(request, erro="Nome é obrigatório.", session=session)
    
    dt_nasc = None
    if data_nascimento:
        try:
            dt_nasc = date.fromisoformat(data_nascimento)
        except ValueError:
            return await configuracoes_titulares_get(request, erro="Data de nascimento inválida.", session=session)

    try:
        await titular_repo.criar_titular(session, nome=nome, tipo=tipo, data_nascimento=dt_nasc)
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await configuracoes_titulares_get(request, erro=f"Erro ao criar titular: {str(e)}", session=session)

    return RedirectResponse(url="/configuracoes/titulares", status_code=303)


# --- Património (Contas e Ativos) ---

@router.get("/configuracoes/patrimonio", response_class=HTMLResponse)
async def configuracoes_patrimonio_get(request: Request, erro: str | None = None, session: AsyncSession = Depends(get_session)):
    titulares = await titular_repo.listar_titulares(session)
    contas = await conta_repo.listar_todas(session)

    # Cada bem mostra a avaliação mais recente (ou projetada) em vez do antigo valor fixo na
    # coluna — ver ava.repositories.ativo_repo.valor_atual, que lê o histórico em ativo_valor.
    ativos = []
    for ativo in await ativo_repo.listar_todos_ativos(session):
        avaliacao = await ativo_repo.valor_atual(session, ativo)
        ativos.append(
            {
                "ativo": ativo,
                "valor": avaliacao.valor if avaliacao else None,
                "e_projetado": avaliacao.e_projetado if avaliacao else False,
                "data_observacao": avaliacao.data_observacao if avaliacao else None,
            }
        )

    # Lista simples (não o dict acima) para preencher o seletor de bem nas contas de dívida.
    ativos_para_ligar = await ativo_repo.listar_todos_ativos(session)

    return templates.TemplateResponse(
        request, "configuracoes_patrimonio.html",
        {
            "titulares": titulares,
            "contas": contas,
            "ativos": ativos,
            "ativos_para_ligar": ativos_para_ligar,
            "erro": erro,
            "total_alertas": await _contar_alertas(session),
            # Alimenta o value/max do campo de data do formulário de saldo declarado — sem isto o
            # campo perde o valor por omissão e o limite superior (não se pode declarar no futuro).
            "hoje": date.today().isoformat(),
        }
    )

@router.post("/configuracoes/contas", response_class=HTMLResponse)
async def configuracoes_contas_post(
    request: Request,
    titular_id: uuid.UUID = Form(...),
    nome: str = Form(...),
    instituicao: str = Form(...),
    tipo: str = Form(...),
    categoria_divida: str = Form(""),
    categoria_investimento: str = Form(""),
    session: AsyncSession = Depends(get_session)
):
    nome = nome.strip()
    instituicao = instituicao.strip()
    
    cat_divida = categoria_divida if tipo in TIPOS_PASSIVO and categoria_divida else None
    cat_invest = categoria_investimento if tipo == "investimento" and categoria_investimento else None

    try:
        await conta_repo.criar_conta(
            session, titular_id=titular_id, instituicao=instituicao,
            tipo=tipo, nome=nome, categoria_divida=cat_divida, categoria_investimento=cat_invest
        )
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await configuracoes_patrimonio_get(request, erro=f"Erro ao criar conta: {str(e)}", session=session)

    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)


@router.post("/configuracoes/contas/{conta_id}/editar", response_class=HTMLResponse)
async def configuracoes_contas_editar_post(
    request: Request,
    conta_id: uuid.UUID,
    titular_id: uuid.UUID = Form(...),
    nome: str = Form(...),
    instituicao: str = Form(...),
    tipo: str = Form(...),
    categoria_divida: str = Form(""),
    categoria_investimento: str = Form(""),
    session: AsyncSession = Depends(get_session)
):
    nome = nome.strip()
    instituicao = instituicao.strip()
    
    cat_divida = categoria_divida if tipo in TIPOS_PASSIVO and categoria_divida else None
    cat_invest = categoria_investimento if tipo == "investimento" and categoria_investimento else None

    try:
        await conta_repo.atualizar_conta(
            session, conta_id=conta_id, titular_id=titular_id, instituicao=instituicao,
            tipo=tipo, nome=nome, categoria_divida=cat_divida, categoria_investimento=cat_invest
        )
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await configuracoes_patrimonio_get(request, erro=f"Erro ao atualizar conta: {str(e)}", session=session)

    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)


@router.post("/configuracoes/contas/{conta_id}/apagar", response_class=HTMLResponse)
async def configuracoes_contas_apagar_post(
    request: Request,
    conta_id: uuid.UUID,
    session: AsyncSession = Depends(get_session)
):
    try:
        await conta_repo.desativar_conta(session, conta_id)
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await configuracoes_patrimonio_get(request, erro=f"Erro ao remover conta: {str(e)}", session=session)

    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)


@router.post("/configuracoes/contas/{conta_id}/ativo")
async def ligar_conta_ao_ativo(
    conta_id: uuid.UUID,
    ativo_id: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    """Liga uma conta de dívida ao bem que financiou. Vazio desliga.

    Restrito a contas de dívida: uma conta à ordem ou de investimento não financiou nada, e
    deixar a ligação disponível nelas só criaria dados sem significado.
    """
    conta = await conta_repo.obter_por_id(session, conta_id)
    if conta is None or conta.tipo not in TIPOS_PASSIVO:
        raise HTTPException(status_code=404, detail="conta de dívida não encontrada")

    novo_ativo_id = None
    if ativo_id.strip():
        try:
            novo_ativo_id = uuid.UUID(ativo_id.strip())
        except ValueError:
            raise HTTPException(status_code=404, detail="ativo não encontrado")
        if await ativo_repo.obter_por_id(session, novo_ativo_id) is None:
            raise HTTPException(status_code=404, detail="ativo não encontrado")

    await conta_repo.definir_ativo(session, conta_id, novo_ativo_id)
    await session.commit()
    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)


@router.post("/configuracoes/contas/{conta_id}/saldo")
async def registar_saldo_manual(
    conta_id: uuid.UUID,
    data: str = Form(...),
    valor: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """O utilizador declara o saldo de uma conta numa data.

    É a segunda e última fonte de âncoras, a par do extrato (spec §7.3). Existe para as contas
    que nunca terão extrato — os cartões de refeição — e para corrigir uma âncora errada: uma
    âncora manual mais recente ofusca as anteriores, porque `obter_saldo_mais_recente` só olha
    para a última.

    Substitui a âncora do mesmo dia em vez de falhar com SaldoDuplicado: corrigir um engano é
    exatamente o caso de uso, e obrigar a apagar primeiro não serviria ninguém.
    """
    conta = await conta_repo.obter_por_id(session, conta_id)
    if conta is None:
        raise HTTPException(status_code=404, detail="conta não encontrada")

    try:
        data_ancora = date.fromisoformat(data.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="data inválida")
    if data_ancora > date.today():
        raise HTTPException(status_code=400, detail="a data não pode ser futura")

    try:
        valor_dec = parse_valor_pt(valor)
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="valor inválido")

    existente = await saldo_historico_repo.obter_saldo_exato(session, conta_id, data_ancora)
    if existente is not None:
        existente.valor = valor_dec
        existente.origem = "manual"
    else:
        await saldo_historico_repo.registar_saldo(
            session, conta_id=conta_id, data=data_ancora, valor=valor_dec, origem="manual"
        )
    await session.commit()
    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)


@router.post("/configuracoes/ativos", response_class=HTMLResponse)
async def configuracoes_ativos_post(
    request: Request,
    titular_id: uuid.UUID = Form(...),
    nome: str = Form(...),
    tipo: str = Form(...),
    valor_atual: str = Form(""),
    data_aquisicao: str = Form(""),
    session: AsyncSession = Depends(get_session)
):
    nome = nome.strip()

    dt_aquisicao = None
    if data_aquisicao:
        try:
            dt_aquisicao = date.fromisoformat(data_aquisicao)
        except ValueError:
            return await configuracoes_patrimonio_get(request, erro="Data de aquisição inválida.", session=session)
        # Esta data alimenta diretamente a avaliação "aquisicao" abaixo (registar_valor). Uma
        # data futura meteria uma observação no futuro em ativo_valor, corrompendo o KPI de
        # património e a série do gráfico da home (ver dashboard.registar_avaliacao_ativo).
        if dt_aquisicao > date.today():
            return await configuracoes_patrimonio_get(request, erro="Data de aquisição não pode ser no futuro.", session=session)

    # O valor introduzido é o preço de compra: vira a primeira observação em ativo_valor, datada
    # da aquisição. Ao contrário de /ativos/novo (que ignora um valor malformado em silêncio),
    # esta rota devolve um erro explícito, como já faz para a data inválida.
    valor_decimal = None
    if valor_atual.strip():
        try:
            valor_decimal = Decimal(valor_atual.strip().replace(",", "."))
        except InvalidOperation:
            valor_decimal = None
        if valor_decimal is None or valor_decimal <= 0:
            return await configuracoes_patrimonio_get(request, erro="Valor inválido.", session=session)

    try:
        ativo = await ativo_repo.criar_ativo(
            session, titular_id=titular_id, nome=nome, tipo=tipo
        )
        if dt_aquisicao:
            ativo.data_aquisicao = dt_aquisicao
        if valor_decimal is not None:
            await ativo_valor_repo.registar_valor(
                session,
                ativo_id=ativo.id,
                data=dt_aquisicao or date.today(),
                valor=valor_decimal,
                origem="aquisicao",
            )
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await configuracoes_patrimonio_get(request, erro=f"Erro ao criar ativo: {str(e)}", session=session)

    return RedirectResponse(url="/configuracoes/patrimonio", status_code=303)
