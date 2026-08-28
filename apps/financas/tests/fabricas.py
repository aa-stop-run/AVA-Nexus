"""Fábricas de objetos para os testes.

Existem para as várias suites falarem a mesma língua: um "movimento manual" tem de significar
exatamente a mesma coisa no teste do casamento e no teste da reconciliação, senão os dois testam
coisas diferentes sem ninguém dar por isso.

`valor` é sempre `str` e convertido aqui com `Decimal(...)`: escrever `Decimal("20.00")` em cada
chamada é ruído, e escrever `20.00` seria um float num projeto que os proíbe.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.categoria import Categoria
from ava.models.conta import Conta
from ava.models.linha_extrato import LinhaExtrato
from ava.models.movimento import Movimento
from ava.models.titular import Titular
from ava.repositories import (categoria_repo, conta_repo, documento_repo, linha_extrato_repo,
                               movimento_repo, titular_repo)

# Contador determinístico para paperless_document_id (unique constraint em Documento — ver
# criar_linha_extrato). Ao nível do módulo, tal como a suite já faz à mão nos outros ficheiros
# de teste (1, 2, 3, 8, 9…), só que sem o operador ter de escolher o próximo número livre.
_proximo_paperless_document_id = itertools.count(1)

# Contador determinístico para o nome do grupo criado por `criar_categoria` — ver o docstring
# dessa função.
_proximo_grupo = itertools.count(1)


async def criar_conta(
    session: AsyncSession, *, titular: Titular, tipo: str = "a_ordem", nome: str = "Ordem"
) -> Conta:
    return await conta_repo.criar_conta(
        session, titular_id=titular.id, instituicao="BPI", tipo=tipo, nome=nome
    )


async def criar_titular_e_conta(
    session: AsyncSession, *, tipo: str = "a_ordem", nome: str = "Ordem"
) -> tuple[Titular, Conta]:
    titular = await titular_repo.criar_titular(session, nome="Nuno", tipo="proprio")
    await session.flush()
    conta = await criar_conta(session, titular=titular, tipo=tipo, nome=nome)
    return titular, conta


async def criar_categoria(
    session: AsyncSession, *, nome: str, tipo: str, natureza: str
) -> Categoria:
    """Uma categoria num grupo próprio, criado na hora.

    Cada chamada cria o seu grupo (nome com contador determinístico) porque
    `uq_categoria_grupo_nome` é sobre (grupo_id, nome): partilhar um grupo entre chamadas obrigava
    cada teste a inventar nomes distintos, e o que os testes da margem querem escolher é a
    NATUREZA, não a arrumação.
    """
    grupo = await categoria_repo.criar_grupo(session, nome=f"Grupo {next(_proximo_grupo)}")
    return await categoria_repo.criar_categoria(
        session, grupo_id=grupo.id, nome=nome, tipo=tipo, natureza=natureza
    )


async def criar_movimento(
    session: AsyncSession,
    *,
    titular: Titular,
    conta: Conta,
    tipo: str,
    valor: str,
    data: date,
    descricao: str = "Mov",
    origem: str = "extrato",
    linha_extrato_id: uuid.UUID | None = None,
    categoria_id: uuid.UUID | None = None,
    ressarcimento_id: uuid.UUID | None = None,
) -> Movimento:
    valor_dec = Decimal(valor)
    return await movimento_repo.criar_movimento(
        session,
        tipo=tipo,
        valor=valor_dec,
        data=data,
        origem=origem,
        descricao=descricao,
        conta_id=conta.id,
        titular_id=titular.id,
        linha_extrato_id=linha_extrato_id,
        linhas=[
            movimento_repo.LinhaNova(
                valor=valor_dec, categoria_id=categoria_id, ressarcimento_id=ressarcimento_id
            )
        ],
    )


async def criar_movimento_manual(
    session: AsyncSession, *, titular: Titular, conta: Conta, valor: str, data: date,
    descricao: str = "Registado a mao",
) -> Movimento:
    """Um movimento como o utilizador o cria em /registo: origem "manual" e SEM linha de extrato.

    A ausência de `linha_extrato_id` é o que o torna "por confirmar" (spec §4) — é a propriedade
    que o casamento procura, por isso está aqui em vez de ser passada em cada teste.
    """
    return await criar_movimento(
        session, titular=titular, conta=conta, tipo="saida", valor=valor, data=data,
        descricao=descricao, origem="manual",
    )


async def criar_movimento_documento(
    session: AsyncSession, *, titular: Titular, valor: str, data: date,
    descricao: str = "Fornecedor", fornecedor_id: uuid.UUID | None = None,
    documento_id: uuid.UUID | None = None,
) -> Movimento:
    """Um movimento como uma fatura o cria (pipeline/faturas.py::_persistir_fatura): origem
    "documento" e SEM conta_id — a fatura não sabe qual conta vai pagá-la, só o extrato/ficheiro
    descobre isso mais tarde (spec da correlação fatura↔extrato, 2026-08-20).
    """
    valor_dec = Decimal(valor)
    return await movimento_repo.criar_movimento(
        session, tipo="saida", valor=valor_dec, data=data, origem="documento",
        descricao=descricao, titular_id=titular.id,
        fornecedor_id=fornecedor_id, documento_id=documento_id,
        linhas=[movimento_repo.LinhaNova(valor=valor_dec)],
    )


async def criar_movimento_regra(
    session: AsyncSession, *, titular: Titular, valor: str, data: date,
    descricao: str = "Recorrente", conta_id: uuid.UUID | None = None,
    categoria_id: uuid.UUID | None = None, recorrente_id: uuid.UUID | None = None,
) -> Movimento:
    """Um movimento como um Recorrente de saída o cria
    (financas/recorrentes.py::gerar_movimentos_recorrentes_do_mes): origem "regra", `valor` é a
    ESTIMATIVA configurada em `Recorrente.valor` -- não é garantido bater certo com o que o banco
    vem a cobrar, ao contrário de `criar_movimento_documento` (uma fatura já traz o valor real).
    `conta_id` é opcional porque `Recorrente.conta_id` também o é.
    """
    valor_dec = Decimal(valor)
    return await movimento_repo.criar_movimento(
        session, tipo="saida", valor=valor_dec, data=data, origem="regra",
        descricao=descricao, titular_id=titular.id, conta_id=conta_id,
        recorrente_id=recorrente_id,
        linhas=[movimento_repo.LinhaNova(valor=valor_dec, categoria_id=categoria_id)],
    )


async def criar_transferencia(
    session: AsyncSession, *, titular: Titular, origem: Conta, destino: Conta,
    valor: str, data: date, manual: bool = False, categoria_id: uuid.UUID | None = None,
) -> Movimento:
    valor_dec = Decimal(valor)
    return await movimento_repo.criar_movimento(
        session,
        tipo="transferencia",
        valor=valor_dec,
        data=data,
        origem="manual" if manual else "extrato",
        descricao="AMORTIZACAO DE CAPITAL",
        conta_id=origem.id,
        conta_destino_id=destino.id,
        titular_id=titular.id,
        linhas=[movimento_repo.LinhaNova(valor=valor_dec, categoria_id=categoria_id)],
    )


async def criar_linha_extrato(
    session: AsyncSession, *, conta: Conta, valor: str, data: date, descricao: str = "LINHA"
) -> LinhaExtrato:
    """Uma linha de extrato pendente. `valor` negativo é uma saída, positivo uma entrada —
    a convenção do extrato, ao contrário de `movimento.valor`, que é sempre positivo.

    `linha_extrato_repo.criar_linha` exige `documento_id` não-nulo (FK NOT NULL no modelo
    LinhaExtrato) — por isso esta fábrica cria primeiro um Documento mínimo, em vez de passar
    None como a interface original assumia. O `paperless_document_id` vem de um contador do
    módulo (não aleatório): a coluna tem unique constraint, e um valor aleatório deixaria uma
    colisão possível — improvável, mas não impossível — numa peça de infraestrutura de que seis
    tarefas dependem, incluindo a Task 8, que chama esta fábrica várias vezes no mesmo teste.
    """
    documento = await documento_repo.criar_documento(
        session,
        paperless_document_id=next(_proximo_paperless_document_id),
        nivel_extracao=0,
        dados_extraidos={},
    )
    return await linha_extrato_repo.criar_linha(
        session, conta_id=conta.id, documento_id=documento.id, data=data,
        valor=Decimal(valor), descricao=descricao,
    )
