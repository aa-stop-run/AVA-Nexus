import pytest

from ava.financas.natureza import (NATUREZAS_DESPESA, NATUREZAS_RECEITA, classificar_fluxo,
                                   natureza_valida, naturezas_de)


def test_naturezas_por_tipo():
    assert naturezas_de("receita") == NATUREZAS_RECEITA
    assert naturezas_de("despesa") == NATUREZAS_DESPESA
    # Um tipo desconhecido não tem naturezas válidas: nada passa a validação, em vez de tudo.
    assert naturezas_de("inventado") == ()


def test_classe_de_conta():
    from ava.financas.natureza import (CLASSE_AUSENTE, CLASSE_CORRENTE, CLASSE_PASSIVO,
                                       CLASSE_POUPANCA, classe_de_conta)

    assert classe_de_conta("a_ordem") == CLASSE_CORRENTE
    assert classe_de_conta("cartao_refeicao") == CLASSE_CORRENTE
    assert classe_de_conta("poupanca") == CLASSE_POUPANCA
    for tipo in ("emprestimo", "cartao_credito", "divida"):
        assert classe_de_conta(tipo) == CLASSE_PASSIVO
    # Sem conta de destino é uma classe própria, não "corrente": significa que o dinheiro saiu
    # do sistema, não que foi para uma conta à ordem.
    assert classe_de_conta(None) == CLASSE_AUSENTE


def test_natureza_valida_amarra_a_natureza_ao_tipo():
    assert natureza_valida(tipo="receita", natureza="recorrente")
    assert natureza_valida(tipo="despesa", natureza="poupanca")
    assert not natureza_valida(tipo="receita", natureza="fixa")
    assert not natureza_valida(tipo="despesa", natureza="recorrente")


@pytest.mark.parametrize(
    "tipo_movimento,origem,destino,esperado",
    [
        # Regras 1 e 2: entrada e saída não olham para contas nenhumas.
        ("entrada", "a_ordem", None, "rendimento"),
        ("entrada", "cartao_credito", None, "rendimento"),
        ("saida", "a_ordem", None, "despesa"),
        # Regra 3: transferência sem destino é despesa a sério — é assim que estão registados os
        # juros de crédito e o imposto de selo, dinheiro que sai e não volta.
        ("transferencia", "a_ordem", None, "despesa"),
        # Regra 5/6: serviço da dívida, nos dois sentidos.
        ("transferencia", "a_ordem", "emprestimo", "divida"),
        ("transferencia", "a_ordem", "cartao_credito", "divida"),
        ("transferencia", "a_ordem", "divida", "divida"),
        ("transferencia", "cartao_credito", "a_ordem", "divida"),
        # Regra 7/8: poupança, nos dois sentidos.
        ("transferencia", "a_ordem", "poupanca", "poupanca"),
        ("transferencia", "poupanca", "a_ordem", "poupanca"),
        # Regra 4: mesma classe dos dois lados não é fluxo nenhum.
        ("transferencia", "a_ordem", "a_ordem", "interno"),
        ("transferencia", "a_ordem", "cartao_refeicao", "interno"),
    ],
)
def test_classificar_fluxo(tipo_movimento, origem, destino, esperado):
    assert classificar_fluxo(
        tipo_movimento=tipo_movimento, tipo_conta_origem=origem, tipo_conta_destino=destino
    ) == esperado


def test_cartao_para_cartao_e_interno_e_nao_servico_da_divida():
    # Existem 3 movimentos assim em produção (59,17 €), hoje contados como despesa. É dívida a
    # mudar de sítio, não dívida a ser paga: a regra 4 tem de correr ANTES da regra 5.
    assert classificar_fluxo(
        tipo_movimento="transferencia",
        tipo_conta_origem="cartao_credito",
        tipo_conta_destino="cartao_credito",
    ) == "interno"


def test_poupanca_para_poupanca_e_interno_e_nao_poupanca():
    # Sem a regra 4 à frente da 7, mover dinheiro entre duas contas poupança inflava a poupança
    # do mês sem nada ter sido poupado.
    assert classificar_fluxo(
        tipo_movimento="transferencia",
        tipo_conta_origem="poupanca",
        tipo_conta_destino="poupanca",
    ) == "interno"


def test_poupanca_para_emprestimo_e_divida_e_nao_poupanca():
    # É as duas coisas ao mesmo tempo (desinvestimento e amortização) e só um valor pode ser
    # devolvido. A amortização é o que a margem tem de cobrir; de onde saiu o dinheiro é uma
    # pergunta separada. Regra 5 antes da regra 8.
    assert classificar_fluxo(
        tipo_movimento="transferencia",
        tipo_conta_origem="poupanca",
        tipo_conta_destino="emprestimo",
    ) == "divida"
