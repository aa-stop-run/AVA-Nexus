from datetime import date
from decimal import Decimal

import pytest

from ava.repositories.margem_repo import margem_estrutural
from tests.fabricas import (criar_categoria, criar_conta, criar_movimento, criar_titular_e_conta,
                            criar_transferencia)

DE = date(2026, 7, 1)
ATE = date(2026, 7, 31)
DIA = date(2026, 7, 15)


@pytest.mark.asyncio
async def test_entrada_recorrente_entra_na_margem(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    salario = await criar_categoria(
        db_session, nome="Salário", tipo="receita", natureza="recorrente"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="2000.00",
        data=DIA, categoria_id=salario.id,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.rendimento_recorrente == Decimal("2000.00")
    assert m.rendimento_extraordinario == Decimal("0")
    assert m.margem == Decimal("2000.00")


@pytest.mark.asyncio
async def test_adiantamento_de_cartao_fica_fora_da_margem(db_session):
    # A razão de ser desta spec: 17 adiantamentos, 8.089,02 €, contados como salário porque o
    # nome do grupo continha "rendimento". O controlo positivo é o que torna este teste válido —
    # sem ele, um repo que devolvesse tudo a zero passava.
    titular, conta = await criar_titular_e_conta(db_session)
    outros = await criar_categoria(
        db_session, nome="Outros", tipo="receita", natureza="extraordinario"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="500.00",
        data=DIA, descricao="CASHADVANCE", categoria_id=outros.id,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.rendimento_extraordinario == Decimal("500.00")
    assert m.rendimento_recorrente == Decimal("0")
    assert m.margem == Decimal("0")


@pytest.mark.asyncio
async def test_despesa_reparte_se_por_fixa_e_variavel(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    renda = await criar_categoria(db_session, nome="Renda", tipo="despesa", natureza="fixa")
    super_ = await criar_categoria(
        db_session, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="700.00", data=DIA,
        categoria_id=renda.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="250.00", data=DIA,
        categoria_id=super_.id,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_fixa == Decimal("700.00")
    assert m.despesa_variavel == Decimal("250.00")
    assert m.margem == Decimal("-950.00")


@pytest.mark.asyncio
async def test_saida_sem_categoria_conta_como_variavel(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="40.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_variavel == Decimal("40.00")
    assert m.despesa_fixa == Decimal("0")


@pytest.mark.asyncio
async def test_transferencia_para_poupanca_nao_e_despesa(db_session):
    # 1.703,00 € em 17 movimentos são contados como despesa hoje. Poupar não é gastar.
    titular, conta = await criar_titular_e_conta(db_session)
    poupanca = await criar_conta(db_session, titular=titular, tipo="poupanca", nome="Poupança")
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=poupanca, valor="100.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.poupanca == Decimal("100.00")
    assert m.despesa_fixa == Decimal("0")
    assert m.despesa_variavel == Decimal("0")
    assert m.margem == Decimal("0")


@pytest.mark.asyncio
async def test_levantar_da_poupanca_subtrai_e_nao_e_rendimento(db_session):
    # O outro lado do mesmo erro: 1.700,00 € contados como rendimento por estarem categorizados
    # em "Outros rendimentos / Outros". Save 100 e levantar 100 tem de dar zero.
    titular, conta = await criar_titular_e_conta(db_session)
    poupanca = await criar_conta(db_session, titular=titular, tipo="poupanca", nome="Poupança")
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=poupanca, valor="100.00", data=DIA,
    )
    await criar_transferencia(
        db_session, titular=titular, origem=poupanca, destino=conta, valor="100.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.poupanca == Decimal("0")
    assert m.rendimento_recorrente == Decimal("0")
    assert m.rendimento_extraordinario == Decimal("0")


@pytest.mark.asyncio
async def test_amortizacoes_vao_para_servico_da_divida(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    emprestimo = await criar_conta(
        db_session, titular=titular, tipo="emprestimo", nome="Crédito Auto"
    )
    cartao = await criar_conta(
        db_session, titular=titular, tipo="cartao_credito", nome="Cartão"
    )
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=emprestimo, valor="300.00", data=DIA,
    )
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=cartao, valor="200.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.servico_divida == Decimal("500.00")
    assert m.despesa_variavel == Decimal("0")
    assert m.margem == Decimal("-500.00")


@pytest.mark.asyncio
async def test_adiantamento_por_transferencia_reduz_servico_divida(db_session):
    # O outro lado do mesmo bug de sinal: um adiantamento de cartão é dinheiro PEDIDO, não pago —
    # reduz o serviço da dívida do mês, não o aumenta. Sem este teste, a condição
    # `classe_origem == CLASSE_PASSIVO` podia inverter-se numa refatoração futura sem que nada
    # apanhasse (a única cobertura até agora era a direção positiva/amortização).
    titular, conta = await criar_titular_e_conta(db_session)
    cartao = await criar_conta(db_session, titular=titular, tipo="cartao_credito", nome="Cartão")

    # Amortização: 300 sobe o serviço da dívida.
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=cartao, valor="300.00", data=DIA,
    )
    # Adiantamento: 100 desce o serviço da dívida.
    await criar_transferencia(
        db_session, titular=titular, origem=cartao, destino=conta, valor="100.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.servico_divida == Decimal("200.00")


@pytest.mark.asyncio
async def test_transferencia_entre_contas_a_ordem_nao_aparece(db_session):
    # A despesa de 30 € é o CONTROLO POSITIVO e é obrigatória: sem ela, um repositório que
    # devolvesse sempre zeros passava neste teste. O que se afirma é que a transferência de 900 €
    # é ignorada ENQUANTO outro movimento do mesmo período continua a ser contado.
    titular, conta = await criar_titular_e_conta(db_session)
    outra = await criar_conta(db_session, titular=titular, tipo="a_ordem", nome="Segunda")
    await criar_transferencia(
        db_session, titular=titular, origem=conta, destino=outra, valor="900.00", data=DIA,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="30.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_variavel == Decimal("30.00")
    assert m.despesa_fixa == Decimal("0")
    assert m.servico_divida == Decimal("0")
    assert m.poupanca == Decimal("0")
    assert m.rendimento_recorrente == Decimal("0")
    assert m.margem == Decimal("-30.00")


@pytest.mark.asyncio
async def test_movimento_repartido_por_duas_naturezas(db_session):
    # É a linha que tem categoria, não o movimento: uma compra de 100 € repartida entre 60 de
    # despesa fixa e 40 de variável tem de aparecer nas duas colunas.
    from ava.repositories import movimento_repo

    titular, conta = await criar_titular_e_conta(db_session)
    fixa = await criar_categoria(db_session, nome="Renda", tipo="despesa", natureza="fixa")
    variavel = await criar_categoria(
        db_session, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await movimento_repo.criar_movimento(
        db_session,
        tipo="saida",
        valor=Decimal("100.00"),
        data=DIA,
        origem="manual",
        descricao="Repartido",
        conta_id=conta.id,
        titular_id=titular.id,
        linhas=[
            movimento_repo.LinhaNova(valor=Decimal("60.00"), categoria_id=fixa.id),
            movimento_repo.LinhaNova(valor=Decimal("40.00"), categoria_id=variavel.id),
        ],
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.despesa_fixa == Decimal("60.00")
    assert m.despesa_variavel == Decimal("40.00")


@pytest.mark.asyncio
async def test_saida_com_natureza_poupanca_sai_da_margem(db_session):
    # natureza="poupanca" existe para reconhecer um reforço de PPR registado como SAÍDA em vez
    # de transferência (spec §3.1, §5) — sem teste, é o único ramo do mapeamento sem rede de
    # segurança, e as categorias reais "Conta Poupança"/"PPR" vão atingi-lo em produção.
    titular, conta = await criar_titular_e_conta(db_session)
    ppr = await criar_categoria(db_session, nome="PPR", tipo="despesa", natureza="poupanca")
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="saida", valor="250.00", data=DIA,
        categoria_id=ppr.id,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.poupanca == Decimal("250.00")
    assert m.despesa_variavel == Decimal("0")
    assert m.despesa_fixa == Decimal("0")
    assert m.margem == Decimal("0")


@pytest.mark.asyncio
async def test_entrada_sem_categoria_conta_como_extraordinaria(db_session):
    # O default seguro do lado da receita (spec §3.3, §5): sem isto, uma inversão futura da
    # condição de natureza podia fazer uma entrada por categorizar contar como recorrente por
    # omissão — o bug de origem, com a suite verde.
    titular, conta = await criar_titular_e_conta(db_session)
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="777.00", data=DIA,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.rendimento_extraordinario == Decimal("777.00")
    assert m.rendimento_recorrente == Decimal("0")
    assert m.margem == Decimal("0")


@pytest.mark.asyncio
async def test_fora_do_intervalo_nao_conta(db_session):
    titular, conta = await criar_titular_e_conta(db_session)
    salario = await criar_categoria(
        db_session, nome="Salário", tipo="receita", natureza="recorrente"
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="2000.00",
        data=date(2026, 6, 30), categoria_id=salario.id,
    )
    await criar_movimento(
        db_session, titular=titular, conta=conta, tipo="entrada", valor="55.00",
        data=DIA, categoria_id=salario.id,
    )

    m = await margem_estrutural(db_session, de=DE, ate=ATE)

    assert m.rendimento_recorrente == Decimal("55.00")
