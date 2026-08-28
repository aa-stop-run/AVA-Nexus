"""Importa um ficheiro de movimentos do banco para o razão.

Três encontros possíveis para cada linha, por esta ordem (spec 2026-08-09, §4):

1. Já existe um movimento de origem "ficheiro" igual → salta. É o caso dominante: cada ficheiro
   cobre semanas para trás e o utilizador importa várias vezes por mês.
2. Existe um movimento manual, uma fatura (origem "documento") ou um recorrente (origem "regra")
   compatível → a versão do banco ganha no texto e na data, e tudo o que já lhe estava ligado
   sobrevive (achado de 2026-08-20: sem incluir "documento", uma fatura processada antes do
   ficheiro cobrir o mesmo período ficava duplicada; sem incluir "regra", o mesmo acontecia a uma
   despesa recorrente de valor variável, que nunca bate certo em valor exato com o real).
3. Não existe → cria, e deixa a categorização automática por padrão fazer o resto.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ava.financas.categorizacao_automatica import padrao_de_descricao
from ava.financas.saldos import JANELA_CASAMENTO_DIAS
from ava.models.movimento import Movimento
from ava.models.saldo_historico import SaldoHistorico
from ava.repositories import conta_repo, movimento_repo, saldo_historico_repo

ORIGEM = "ficheiro"

# Banda de plausibilidade para casar um "regra" (recorrente) com a linha real do banco -- ao
# contrário de "documento" (o valor de uma fatura já É o valor real, do OCR do Paperless), o valor
# de um "regra" é a ESTIMATIVA configurada em `Recorrente.valor`, que só por coincidência bate
# certo com o que o banco cobra (uma conta de eletricidade variável, por exemplo). Exigir
# igualdade exata aqui deixava passar exatamente o caso que motivou este fix: um recorrente de
# valor variável nunca seria reconhecido como já registado, duplicando-se a cada importação --
# mesma classe do bug do EDP (`documento`), corrigido nesta sessão. Mesmo raciocínio e a mesma
# banda de `insights_repo._BANDA_PLAUSIBILIDADE` (spec 2026-08-20-insights-financeiros-design §6.1).
_BANDA_PLAUSIBILIDADE_REGRA = Decimal("0.5")

# (data, |valor|, descrição, tipo). O `tipo` faz parte da chave pela MESMA razão que já obrigou a
# acrescentá-lo a `_manual_compativel` (Important #1 da ronda de correção 1): `movimento.valor` é
# sempre positivo, por isso o valor sozinho não distingue uma entrada de uma saída — um débito e o
# seu estorno com a mesma data, valor absoluto e texto ficariam na MESMA chave sem isto, e um dos
# dois seria saltado por engano enquanto o outro duplicava (revisão final, achado 4).
_Chave = tuple[date, Decimal, str, str]


def _tipo_de(mov: MovimentoFicheiro) -> str:
    return "entrada" if mov.valor > 0 else "saida"


class ResultadoImportacao(NamedTuple):
    criados: int
    casados: int
    # Linhas que JÁ existiam como movimento "ficheiro" de uma importação anterior (spec §4.1) —
    # a mesma linha, relida.
    saltados: int
    # Linhas anteriores ou iguais à última âncora de extrato desta conta (revisão da revisão
    # final, achado do minor sobre a mensagem) — nunca chegaram a existir como movimento; foram
    # descartadas por o extrato já ter coberto esse período. Contador PRÓPRIO porque a frase que
    # descreve cada um é diferente e verdadeira só para o seu caso: dizer "já existiam" sobre
    # estas seria falso — na primeira importação a seguir a um extrato, a maioria das linhas do
    # ficheiro cai aqui, nunca tendo existido como movimento nenhum.
    cobertos_pelo_extrato: int
    ancora: SaldoHistorico | None


async def _contar_existentes_por_chave(
    session: AsyncSession, movimentos: list[MovimentoFicheiro], conta_id: uuid.UUID
) -> dict[_Chave, int]:
    """Quantos movimentos de origem "ficheiro" já existiam, por (data, valor, descrição, tipo),
    ANTES de esta importação começar (spec §4.1).

    Uma fotografia tirada uma vez, antes do laço de `importar` — não uma consulta repetida a
    cada linha. `movimento_repo.criar_movimento` faz `flush()`, por isso um movimento criado na
    iteração N já ficaria visível a uma consulta da iteração N+1: duas linhas rigorosamente
    iguais no mesmo ficheiro (mesma data, valor e descrição — duas transações reais que o banco
    relatou da mesma forma) colapsariam, a segunda lida como "já existe" quando na verdade nunca
    tinha existido antes desta chamada (Critical/Important #3, ronda de correção 1). Contar por
    MULTIPLICIDADE em vez de por existência resolve isto: N linhas iguais no ficheiro menos M já
    na base dão as N-M que faltam criar.
    """
    if not movimentos:
        return {}
    chaves = {(mov.data, abs(mov.valor), mov.descricao, _tipo_de(mov)) for mov in movimentos}
    datas = {chave[0] for chave in chaves}
    resultado = await session.execute(
        select(Movimento.data, Movimento.valor, Movimento.descricao, Movimento.tipo).where(
            Movimento.conta_id == conta_id,
            Movimento.origem == ORIGEM,
            Movimento.data.in_(datas),
        )
    )
    contagem: dict[_Chave, int] = {}
    for data_existente, valor_existente, descricao_existente, tipo_existente in resultado.all():
        chave = (data_existente, valor_existente, descricao_existente, tipo_existente)
        if chave in chaves:
            contagem[chave] = contagem.get(chave, 0) + 1
    return contagem


async def _compativel(
    session: AsyncSession, mov: MovimentoFicheiro, conta_id: uuid.UUID, tipo: str
) -> Movimento | None:
    """Um movimento registado à mão, ou uma fatura, que seja esta mesma transação (spec §4.2).

    Valor exato e data dentro de ±`JANELA_CASAMENTO_DIAS` — nunca por descrição, porque aqui as
    fontes são diferentes: o utilizador escreveu "Compras no Marec" e o banco escreveu
    "01/08 COMPRA ELEC 2311263/46 MAREC".

    Três origens candidatas, com a mesma janela de data mas condições de conta e de valor
    diferentes:
    - manual: já sabe a conta (o utilizador escolheu-a no formulário), por isso exige-se
      igualdade exata de conta e de valor.
    - documento (fatura): nunca sabe a conta que a vai pagar (`_persistir_fatura` nunca passa
      `conta_id`), por isso só é candidata enquanto ainda não tiver nenhuma — achado de
      2026-08-20, caso real: fatura EDP de 83,39€ processada antes do ficheiro do banco cobrir o
      mesmo pagamento, duplicada por nada ver a fatura como já registada. O valor de uma fatura já
      é o valor real (OCR do Paperless), por isso continua a exigir-se igualdade exata.
    - regra (recorrente): pode já saber a conta (`Recorrente.conta_id`, se configurada) ou não.
      O valor NUNCA é exigido exato -- é a estimativa de `Recorrente.valor`, não o valor real, e
      só por coincidência bate certo com o que o banco cobra (ex. uma conta de eletricidade
      variável). Usa `_BANDA_PLAUSIBILIDADE_REGRA` em vez disso -- achado de 2026-08-20, mesma
      classe do bug do EDP mas para despesas recorrentes: sem isto, um recorrente de valor
      variável nunca seria reconhecido como já registado, duplicando-se a cada importação.

    Desempate determinístico (data mais próxima, depois id), igual ao de `casamento.casar_linha`.
    """
    inicio = mov.data - timedelta(days=JANELA_CASAMENTO_DIAS)
    fim = mov.data + timedelta(days=JANELA_CASAMENTO_DIAS)
    valor_abs = abs(mov.valor)
    resultado = await session.execute(
        select(Movimento)
        .options(selectinload(Movimento.linhas))
        .where(
            or_(
                and_(
                    Movimento.origem.in_(movimento_repo.ORIGENS_REGISTO_MANUAL),
                    Movimento.conta_id == conta_id,
                    Movimento.valor == valor_abs,
                ),
                and_(
                    Movimento.origem == "documento",
                    Movimento.conta_id.is_(None),
                    Movimento.valor == valor_abs,
                ),
                and_(
                    Movimento.origem == "regra",
                    or_(Movimento.conta_id == conta_id, Movimento.conta_id.is_(None)),
                    Movimento.valor >= valor_abs * (Decimal("1") - _BANDA_PLAUSIBILIDADE_REGRA),
                    Movimento.valor <= valor_abs * (Decimal("1") + _BANDA_PLAUSIBILIDADE_REGRA),
                ),
            ),
            # `movimento.valor` é sempre positivo — o valor sozinho não distingue uma entrada de
            # uma saída. Sem esta condição, um reembolso manual (entrada) do mesmo valor podia
            # "casar" com uma compra do ficheiro (saída), invertendo o sinal do dinheiro (Critical
            # #1, ronda de correção 1). `tipo` já vem calculado do sinal de `mov.valor` e nunca é
            # "transferencia" — mas a exclusão fica explícita porque uma transferência manual tem
            # `conta_destino_id` preenchido e o ficheiro só mostra uma perna da operação: deixá-la
            # entrar aqui e reescrever-lhe a descrição/data corromperia as duas pontas.
            Movimento.tipo == tipo,
            Movimento.tipo != "transferencia",
            Movimento.data >= inicio,
            Movimento.data <= fim,
            # Um movimento já ligado a uma linha de extrato já foi confirmado pelo banco — não é
            # "por confirmar" nenhum. Sem isto, e como o ficheiro cobre semanas para trás e se
            # sobrepõe ao período do extrato, um movimento manual JÁ confirmado (origem ainda
            # "manual", mas com linha_extrato_id preenchido por `casamento.casar_linha`, que não
            # muda a origem) seria "casado" outra vez pelo ficheiro, sequestrando o registo bom e
            # deixando o movimento real do ficheiro sem par (Important #2, ronda de correção 1).
            Movimento.linha_extrato_id.is_(None),
        ).order_by(Movimento.data, Movimento.id)
    )
    candidatos = list(resultado.scalars().all())
    if not candidatos:
        return None
    candidatos.sort(key=lambda m: (abs((m.data - mov.data).days), m.data, m.id))
    return candidatos[0]


async def importar(
    session: AsyncSession, ficheiro: FicheiroMovimentos, *, conta_id: uuid.UUID
) -> ResultadoImportacao:
    """Importa os movimentos e regista a âncora. Não faz commit — o chamador é que decide."""
    conta = await conta_repo.obter_por_id(session, conta_id)
    criados = casados = saltados = 0

    # Sobreposição com o extrato (revisão final, achado 3): até à data do último extrato desta
    # conta, o extrato é a fonte de verdade e já cobriu tudo. O que o ficheiro traz desse período
    # ou já lá está (como movimento ou como reconciliação) ou é ruído — e o ficheiro é provisório,
    # nunca corrige o definitivo. Sem isto, a deduplicação e o casamento acima só viam
    # origem="ficheiro" e ORIGENS_REGISTO_MANUAL, nunca "extrato" — e como o BPI Net exporta ~seis
    # semanas para trás, TODOS os meses o extrato cria movimentos para a cauda que as importações
    # não cobriram, e a exportação seguinte volta a trazer essa mesma cauda: duplicação silenciosa,
    # mensal, não só um risco da primeira importação.
    #
    # Contador PRÓPRIO (`cobertos_pelo_extrato`, não `saltados`): estas linhas nunca chegaram a
    # existir como movimento — "já existiam" seria falso sobre elas (revisão da revisão final).
    ancora_extrato = await saldo_historico_repo.obter_saldo_mais_recente_por_origem(
        session, conta_id, origem="extrato"
    )
    limite_extrato = ancora_extrato.data if ancora_extrato is not None else None
    movimentos_a_processar = [
        mov for mov in ficheiro.movimentos
        if limite_extrato is None or mov.data > limite_extrato
    ]
    cobertos_pelo_extrato = len(ficheiro.movimentos) - len(movimentos_a_processar)

    ja_existentes = await _contar_existentes_por_chave(session, movimentos_a_processar, conta_id)
    vistos: dict[_Chave, int] = {}

    for mov in movimentos_a_processar:
        tipo = _tipo_de(mov)
        chave = (mov.data, abs(mov.valor), mov.descricao, tipo)
        posicao = vistos.get(chave, 0)
        vistos[chave] = posicao + 1
        if posicao < ja_existentes.get(chave, 0):
            # Esta linha corresponde a uma das M cópias que já existiam ANTES desta importação
            # começar — as primeiras M ocorrências da chave "saltam"; quaisquer outras a mais
            # (linhas N-M) são transações novas e seguem para os encontros 2/3 abaixo.
            saltados += 1
            continue

        existente = await _compativel(session, mov, conta_id, tipo)
        if existente is not None:
            # A versão do banco ganha no texto e na data. `categoria_id`, `ativo_id` e
            # `conta_relacionada_id` das linhas NÃO se tocam: o banco não sabe nada disso.
            # `conta_id` é sempre reescrito: para um manual já é o mesmo valor (no-op), e para
            # uma fatura ou um recorrente é o preenchimento (ou a confirmação) da conta.
            existente.descricao = mov.descricao
            existente.data = mov.data
            existente.origem = ORIGEM
            existente.conta_id = conta_id
            if existente.valor != abs(mov.valor):
                # Só acontece para "regra": manual e documento só chegam aqui com valor já igual
                # (_compativel exige-o). O valor de um recorrente é a estimativa configurada, não
                # o real -- agora que o banco confirmou o valor verdadeiro, substitui-se nos dois
                # sítios onde o valor vive: o movimento E a sua única linha (sempre uma só, um
                # "regra" nunca é dividido por categorias -- gerar_movimentos_recorrentes_do_mes
                # cria-o sempre com uma linha). Sem tocar na linha, os totais por categoria (que
                # somam MovimentoLinha.valor, não Movimento.valor) continuavam presos à estimativa
                # antiga.
                existente.linhas[0].valor = abs(mov.valor)
                existente.valor = abs(mov.valor)
            casados += 1
            continue

        categoria_id = await movimento_repo.obter_categoria_mais_recente_por_padrao(
            session, tipo=tipo, padrao=padrao_de_descricao(mov.descricao), conta_id=conta_id
        )
        await movimento_repo.criar_movimento(
            session,
            tipo=tipo,
            # movimento.valor é sempre positivo; o sinal vive no tipo.
            valor=abs(mov.valor),
            data=mov.data,
            origem=ORIGEM,
            descricao=mov.descricao,
            conta_id=conta_id,
            titular_id=conta.titular_id if conta is not None else None,
            linhas=[movimento_repo.LinhaNova(valor=abs(mov.valor), categoria_id=categoria_id)],
        )
        criados += 1

    ancora = await _registar_ancora(session, ficheiro, conta_id)
    return ResultadoImportacao(
        criados=criados, casados=casados, saltados=saltados,
        cobertos_pelo_extrato=cobertos_pelo_extrato, ancora=ancora,
    )


async def _registar_ancora(
    session: AsyncSession, ficheiro: FicheiroMovimentos, conta_id: uuid.UUID
) -> SaldoHistorico | None:
    """Grava o saldo declarado pelo banco como âncora (spec §2.1, §2.2).

    Hierarquia de confiança: `extrato` > `ficheiro` > `manual`. Uma âncora de extrato na mesma
    data FICA — o extrato é a fonte de verdade e o ficheiro é provisório. Qualquer outra é
    substituída.

    Uma âncora que não se escreve nunca impede os movimentos de entrar: eles são o objetivo.
    """
    existente = await saldo_historico_repo.obter_saldo_exato(session, conta_id, ficheiro.data_saldo)
    if existente is not None:
        if existente.origem == "extrato":
            return None
        existente.valor = ficheiro.saldo_declarado
        existente.origem = ORIGEM
        return existente

    return await saldo_historico_repo.registar_saldo(
        session, conta_id=conta_id, data=ficheiro.data_saldo,
        valor=ficheiro.saldo_declarado, origem=ORIGEM,
    )
