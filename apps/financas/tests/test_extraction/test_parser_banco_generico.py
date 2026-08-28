import logging
from datetime import date
from decimal import Decimal

from ava.extraction.parsers.banco_generico import parse_banco_generico

TEXTO_EXTRATO_TIPICO = """
Banco: CGD
Conta: Conta à Ordem
Saldo inicial: 1000,00 EUR
Saldo em 31/07/2026: 1350,00 EUR
Movimentos:
01/07/2026 | -45,67 | DD EDP COMERCIAL
15/07/2026 | 1500,00 | ORDENADO EMPRESA XPTO
20/07/2026 | -12,50 | COMPRA CONTINENTE
"""


def test_parse_banco_generico_extrai_saldo_e_movimentos():
    extrato = parse_banco_generico(TEXTO_EXTRATO_TIPICO)

    assert extrato is not None
    assert extrato.instituicao == "CGD"
    assert extrato.tipo_conta == "a_ordem"
    assert extrato.saldo_final.data == date(2026, 7, 31)
    assert extrato.saldo_final.valor == Decimal("1350.00")
    assert len(extrato.movimentos) == 3
    assert extrato.movimentos[0].valor == Decimal("-45.67")
    assert extrato.movimentos[1].valor == Decimal("1500.00")
    assert extrato.movimentos[2].descricao == "COMPRA CONTINENTE"
    # A-P6: um extrato totalmente limpo não reporta nenhuma linha descartada.
    assert extrato.linhas_nao_reconhecidas == 0


def test_parser_extrai_saldo_inicial():
    # Necessário para o checksum de validar_extrato (§7): saldo_final − saldo_inicial ==
    # Σ(movimentos). Padrão isolado em banco_generico._SALDO_INICIAL (pendente de ajuste na
    # Tarefa 10, quando houver extratos reais para confirmar o formato exato).
    extrato = parse_banco_generico(TEXTO_EXTRATO_TIPICO)

    assert extrato is not None
    assert extrato.saldo_inicial == Decimal("1000.00")


def test_parser_devolve_saldo_inicial_none_quando_secao_ausente():
    # Nem todo extrato real vai ter esta secção (pendente da Tarefa 10) — o parser não deve
    # inventar um valor; ausência do padrão fica None, e validar_extrato trata isso como extrato
    # não verificável (A-P3), não como um erro do parser.
    texto_sem_saldo_inicial = TEXTO_EXTRATO_TIPICO.replace("Saldo inicial: 1000,00 EUR\n", "")
    extrato = parse_banco_generico(texto_sem_saldo_inicial)

    assert extrato is not None
    assert extrato.saldo_inicial is None


def test_parse_banco_generico_devolve_none_para_texto_nao_reconhecido():
    assert parse_banco_generico("um documento qualquer sem os campos esperados") is None


# --- Exception-safety: campos obrigatorios (conta/saldo) invalidos derrubam o extrato inteiro ---
# Segue a convencao estabelecida em edp.py/agua.py: um regex pode bater na "forma" de uma data
# ou de um numero sem o valor ser convertivel (datetime.strptime/Decimal levantam), e o parser
# nunca deve propagar essa excecao — deve degradar para None (secao obrigatoria) ou omitir o
# item problematico (movimento individual, ver testes abaixo).

TEXTO_SALDO_DATA_INVALIDA = TEXTO_EXTRATO_TIPICO.replace(
    "Saldo em 31/07/2026: 1350,00 EUR",
    "Saldo em 31/04/2026: 1350,00 EUR",
)


def test_parse_banco_generico_devolve_none_quando_data_do_saldo_invalida():
    # "31/04/2026" corresponde ao formato \d{2}/\d{2}/\d{4} mas abril só tem 30 dias:
    # datetime.strptime levanta ValueError. O saldo final é uma secao obrigatoria do
    # extrato (nao ha extrato sem saldo valido), por isso o parser inteiro devolve None.
    assert parse_banco_generico(TEXTO_SALDO_DATA_INVALIDA) is None


TEXTO_SALDO_VALOR_INVALIDO = TEXTO_EXTRATO_TIPICO.replace(
    "Saldo em 31/07/2026: 1350,00 EUR",
    "Saldo em 31/07/2026: 99,999,99 EUR",
)


def test_parse_banco_generico_devolve_none_quando_valor_do_saldo_invalido():
    # "99,999,99" nao é um número válido em português (demasiados separadores):
    # Decimal levanta InvalidOperation. Mesmo raciocínio: o saldo é obrigatório.
    assert parse_banco_generico(TEXTO_SALDO_VALOR_INVALIDO) is None


# --- Exception-safety: uma linha de movimento garbled degrada só essa linha, nao o extrato ---
# Ao contrário do saldo/secao de conta (obrigatórios), a lista de movimentos é best-effort:
# um único OCR mal interpretado numa linha de movimento nao deve fazer perder o extrato inteiro
# (instituição + saldo final continuam corretos e úteis). O parser salta a linha problemática e
# mantém as restantes — mas NUNCA em silêncio (A-P6): fica registada no log (logger "ava.extraction")
# e contabilizada em `linhas_nao_reconhecidas`, para quem consome o extrato saber que faltam dados.

TEXTO_MOVIMENTO_DATA_INVALIDA = TEXTO_EXTRATO_TIPICO.replace(
    "01/07/2026 | -45,67 | DD EDP COMERCIAL",
    "31/04/2026 | -45,67 | DD EDP COMERCIAL",
)


def test_parse_banco_generico_omite_movimento_com_data_invalida_mas_mantem_o_resto():
    extrato = parse_banco_generico(TEXTO_MOVIMENTO_DATA_INVALIDA)

    assert extrato is not None
    assert extrato.saldo_final.valor == Decimal("1350.00")
    assert len(extrato.movimentos) == 2
    assert extrato.movimentos[0].descricao == "ORDENADO EMPRESA XPTO"
    assert extrato.movimentos[1].descricao == "COMPRA CONTINENTE"
    # A-P6: a linha descartada tem de ficar contabilizada no schema, não só omitida da lista.
    assert extrato.linhas_nao_reconhecidas == 1


def test_parse_banco_generico_regista_aviso_no_log_quando_omite_movimento(caplog):
    # A-P6: falha de ingestão nunca é silenciosa — além do campo estrutural
    # (linhas_nao_reconhecidas), tem de existir sinal para o operador no log.
    with caplog.at_level(logging.WARNING, logger="ava.extraction"):
        extrato = parse_banco_generico(TEXTO_MOVIMENTO_DATA_INVALIDA)

    assert extrato is not None
    avisos = [
        registro
        for registro in caplog.records
        if registro.levelname == "WARNING" and "31/04/2026" in registro.message
    ]
    assert len(avisos) == 1


TEXTO_MOVIMENTO_VALOR_INVALIDO = TEXTO_EXTRATO_TIPICO.replace(
    "15/07/2026 | 1500,00 | ORDENADO EMPRESA XPTO",
    "15/07/2026 | 1.500,00,00 | ORDENADO EMPRESA XPTO",
)


def test_parse_banco_generico_omite_movimento_com_valor_invalido_mas_mantem_o_resto():
    extrato = parse_banco_generico(TEXTO_MOVIMENTO_VALOR_INVALIDO)

    assert extrato is not None
    assert len(extrato.movimentos) == 2
    assert extrato.movimentos[0].descricao == "DD EDP COMERCIAL"
    assert extrato.movimentos[1].descricao == "COMPRA CONTINENTE"
    assert extrato.linhas_nao_reconhecidas == 1


def test_parse_banco_generico_devolve_extrato_com_movimentos_vazios_quando_nenhum_bate():
    texto_sem_movimentos = """
Banco: CGD
Conta: Conta à Ordem
Saldo em 31/07/2026: 1350,00 EUR
Movimentos:
sem linhas no formato esperado aqui
"""
    extrato = parse_banco_generico(texto_sem_movimentos)

    assert extrato is not None
    assert extrato.movimentos == []
    # A linha "sem linhas no formato esperado aqui" nem sequer bate no regex de movimento
    # (não tem a forma data|valor|descricao), por isso não é uma linha "descartada" — é
    # simplesmente ausente do documento. linhas_nao_reconhecidas conta só as que batem na
    # forma mas falham a conversão (ver testes acima).
    assert extrato.linhas_nao_reconhecidas == 0


# --- Fix 8: _inferir_tipo_conta não pode assumir cartao_refeicao para qualquer "cartão" ---
# Um cartão de CRÉDITO é uma dívida (tipo="divida"), não um ativo tipo cartao_refeicao — a
# heurística antiga classificava ambos da mesma forma. Um "cartão" genérico (nem crédito nem
# refeição/alimentação) é ambíguo e não deve ser adivinhado — cai no mesmo fallback a_ordem do
# caso sem palavra-chave nenhuma.


def _extrato_com_conta(nome_conta: str):
    texto = TEXTO_EXTRATO_TIPICO.replace("Conta: Conta à Ordem", f"Conta: {nome_conta}")
    return parse_banco_generico(texto)


def test_parse_banco_generico_infere_cartao_de_credito_como_divida():
    extrato = _extrato_com_conta("Cartão de Crédito")
    assert extrato is not None
    assert extrato.tipo_conta == "divida"


def test_parse_banco_generico_infere_cartao_refeicao():
    extrato = _extrato_com_conta("Cartão Refeição Edenred")
    assert extrato is not None
    assert extrato.tipo_conta == "cartao_refeicao"


def test_parse_banco_generico_infere_poupanca():
    extrato = _extrato_com_conta("Conta Poupança")
    assert extrato is not None
    assert extrato.tipo_conta == "poupanca"


def test_parse_banco_generico_infere_a_ordem_para_conta_generica():
    extrato = _extrato_com_conta("Conta à Ordem")
    assert extrato is not None
    assert extrato.tipo_conta == "a_ordem"


def test_parse_banco_generico_cartao_generico_ambiguo_nao_adivinha_refeicao():
    # "cartão" sozinho (nem "crédito" nem "refeição"/"alimentação") é genuinamente ambíguo —
    # antes da Fix 8 isto caía silenciosamente em cartao_refeicao por omissão.
    extrato = _extrato_com_conta("Cartão Nubank")
    assert extrato is not None
    assert extrato.tipo_conta == "a_ordem"
