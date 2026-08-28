from ava.financas.categorizacao_automatica import padrao_de_descricao


def test_padrao_substitui_sequencias_de_digitos_por_marcador():
    assert padrao_de_descricao("COMPRA ELEC 2311263/47 MERCADONA GONDOMAR") == (
        "COMPRA ELEC #/# MERCADONA GONDOMAR"
    )


def test_padrao_e_insensivel_a_maiusculas():
    assert padrao_de_descricao("compra elec 123 loja x") == padrao_de_descricao("COMPRA ELEC 456 LOJA X")


def test_padrao_colapsa_espacos_repetidos():
    assert padrao_de_descricao("DD   FORNECEDOR   123") == "DD FORNECEDOR #"


def test_padroes_com_referencias_diferentes_sao_iguais():
    a = padrao_de_descricao("DD SOLINCA CLASSIC,SA 00054869949")
    b = padrao_de_descricao("DD SOLINCA CLASSIC,SA 00054870021")
    assert a == b


def test_padroes_de_comerciantes_diferentes_nao_sao_iguais():
    a = padrao_de_descricao("COMPRA ELEC 123 MERCADONA GONDOMAR")
    b = padrao_de_descricao("COMPRA ELEC 456 PINGO DOCE MAIA")
    assert a != b
