"""A margem estrutural do período: o rendimento fiável contra os compromissos que ele tem de pagar.

Não escreve nada — é uma leitura agregada, calculada a cada pedido, como `divergencia_repo`.

A agregação corre em Python e não em SQL de propósito: a classificação de fluxo vive em
`financas/natureza.py` e é a única fonte de verdade sobre ela. Reescrevê-la como `CASE WHEN`
duplicava a regra em dois sítios com linguagens diferentes, e a ordem das regras — que é a parte
subtil (spec §4) — deixava de ser testável em isolamento. O volume é de centenas de linhas por
mês, não de milhões.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ava.financas.natureza import (CLASSE_PASSIVO, CLASSE_POUPANCA, classe_de_conta,
                                   classificar_fluxo)
from ava.models.categoria import Categoria
from ava.models.conta import Conta
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.repositories import ressarcimento_repo

_ZERO = Decimal("0")


class MargemEstrutural(NamedTuple):
    """O período resumido em sete números. Todos positivos, exceto `margem` e `poupanca`."""

    rendimento_recorrente: Decimal
    rendimento_extraordinario: Decimal
    despesa_fixa: Decimal
    despesa_variavel: Decimal
    servico_divida: Decimal
    poupanca: Decimal
    margem: Decimal


async def margem_estrutural(
    session: AsyncSession,
    *,
    de: date,
    ate: date,
    titular_id: uuid.UUID | None = None,
) -> MargemEstrutural:
    """Os sete números do período [de, ate], ambos inclusive.

    `margem = rendimento_recorrente − despesa_fixa − despesa_variavel − servico_divida`.

    A poupança NÃO entra na margem: é o que se faz com a margem, não uma condição para a ter.

    Percorre `movimento_linha` e não `movimento` porque um movimento pode estar repartido por
    várias categorias, e é a linha que tem `categoria_id` — uma compra de 100 € repartida entre
    renda e supermercado tem de aparecer nas duas colunas.

    Uma linha sem categoria segue o default seguro (spec §3.3): numa saída conta como variável,
    numa entrada como extraordinária. Não contar como fiável aquilo que ainda nem categoria tem é
    o erro seguro.
    """
    ContaOrigem = aliased(Conta)
    ContaDestino = aliased(Conta)

    stmt = (
        select(
            Movimento.tipo,
            MovimentoLinha.valor,
            Categoria.natureza,
            ContaOrigem.tipo,
            ContaDestino.tipo,
            MovimentoLinha.ressarcimento_id,
        )
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .outerjoin(Categoria, Categoria.id == MovimentoLinha.categoria_id)
        .outerjoin(ContaOrigem, ContaOrigem.id == Movimento.conta_id)
        .outerjoin(ContaDestino, ContaDestino.id == Movimento.conta_destino_id)
        .where(Movimento.data >= de, Movimento.data <= ate)
    )
    if titular_id is not None:
        stmt = stmt.where(Movimento.titular_id == titular_id)

    linhas = list(await session.execute(stmt))

    ids_ressarcimento = {
        ressarcimento_id for *_resto, ressarcimento_id in linhas if ressarcimento_id is not None
    }
    resumos = {
        rid: await ressarcimento_repo.resumo(session, rid) for rid in ids_ressarcimento
    }

    totais = {
        "rendimento_recorrente": _ZERO,
        "rendimento_extraordinario": _ZERO,
        "despesa_fixa": _ZERO,
        "despesa_variavel": _ZERO,
        "servico_divida": _ZERO,
        "poupanca": _ZERO,
    }

    for tipo_mov, valor, natureza, tipo_origem, tipo_destino, ressarcimento_id in linhas:
        fluxo = classificar_fluxo(
            tipo_movimento=tipo_mov,
            tipo_conta_origem=tipo_origem,
            tipo_conta_destino=tipo_destino,
        )

        if fluxo == "interno":
            continue

        # Ressarcimento (spec 2026-08-14, §4.1): só desconta/exclui quando o grupo tem
        # exatamente UMA despesa — regra única, sem exceções, porque com 0 ou 2+ despesas não há
        # forma não-arbitrária de saber qual foi coberta.
        resumo_grupo = resumos.get(ressarcimento_id) if ressarcimento_id is not None else None
        grupo_simples = resumo_grupo is not None and resumo_grupo.n_despesas == 1

        if fluxo == "rendimento" and grupo_simples:
            # Já contabilizado via a despesa que desconta — não soma a nenhuma das duas colunas.
            continue

        if fluxo == "rendimento":
            coluna = (
                "rendimento_recorrente"
                if natureza == "recorrente"
                else "rendimento_extraordinario"
            )
        elif fluxo == "despesa":
            # A natureza "poupanca" numa saída é o que permite reconhecer um reforço de PPR
            # registado como saída em vez de transferência (spec §5).
            coluna = {"fixa": "despesa_fixa", "poupanca": "poupanca"}.get(
                natureza, "despesa_variavel"
            )
        elif fluxo == "divida":
            coluna = "servico_divida"
        else:
            coluna = "poupanca"

        # O SINAL vem da direção, não da classificação: sair de uma conta de poupança é
        # despoupar, e sair de um passivo é pedir emprestado. Save 100 e levantar 100 tem de
        # dar zero, não 200 — e um adiantamento de cartão REDUZ o serviço da dívida do mês,
        # porque é dinheiro pedido e não pago.
        classe_origem = classe_de_conta(tipo_origem)
        sinal = 1
        if fluxo == "poupanca" and classe_origem == CLASSE_POUPANCA:
            sinal = -1
        elif fluxo == "divida" and classe_origem == CLASSE_PASSIVO:
            sinal = -1

        valor_efetivo = valor
        if fluxo == "despesa" and grupo_simples:
            # O grupo só tem esta despesa — o líquido do grupo INTEIRO é o valor efetivo desta
            # linha, porque não há mais nenhuma despesa a repartir com.
            valor_efetivo = resumo_grupo.liquido

        totais[coluna] += sinal * valor_efetivo

    margem = (
        totais["rendimento_recorrente"]
        - totais["despesa_fixa"]
        - totais["despesa_variavel"]
        - totais["servico_divida"]
    )
    return MargemEstrutural(**totais, margem=margem)
