import pytest
from datetime import datetime, timezone
from saude.extracao.parser_email_saude import extrair_marcacao_saude, MarcacaoExtraida


def test_extrair_consulta_cuf():
    texto = """
    Exmo(a) Sr(a) aa-stop-run,
    Confirmamos a sua marcação de Consulta de Oftalmologia com o(a) Dr(a). Maria João Santos
    no dia 15/10/2026 às 10:30 no Hospital CUF Descobertas.
    Código de marcação: CUF-98231.
    """
    resultado = extrair_marcacao_saude(texto)
    assert resultado is not None
    assert resultado.tipo == "consulta"
    assert resultado.nome_paciente == "aa-stop-run"
    assert resultado.especialidade == "Oftalmologia"
    assert "Maria João Santos" in resultado.medico
    assert resultado.local_clinica is not None
    assert resultado.data_hora == datetime(2026, 10, 15, 10, 30, tzinfo=timezone.utc)
    assert resultado.codigo_confirmacao == "CUF-98231"


def test_extrair_consulta_luz_saude():
    texto = """
    Confirmação de Agendamento
    Olá Member,
    Confirmamos a sua Consulta de Dermatologia com a Drª. Ana Rita Ferreira
    para 22/11/2026 às 14:00 no Hospital da Luz Lisboa.
    Recomendações: Trazer análises anteriores.
    """
    resultado = extrair_marcacao_saude(texto)
    assert resultado is not None
    assert resultado.nome_paciente == "Member"
    assert resultado.especialidade == "Dermatologia"
    assert resultado.local_clinica is not None
    assert resultado.data_hora == datetime(2026, 11, 22, 14, 0, tzinfo=timezone.utc)


def test_extrair_pediatria_charlie():
    texto = """
    Marcação para Junior:
    Consulta de Pediatria no Centro de Saúde dia 05/11/2026 às 11:15
    Médico: Drª Teresa Ramos.
    """
    resultado = extrair_marcacao_saude(texto)
    assert resultado is not None
    assert resultado.nome_paciente == "Junior"
    assert resultado.especialidade == "Pediatria"
    assert resultado.data_hora == datetime(2026, 11, 5, 11, 15, tzinfo=timezone.utc)


def test_extrair_analises_clinicas():
    texto = """
    Marcação de Análises Clínicas para aa-stop-run:
    Exame de Análises de Sangue e Urina no dia 18/09/2026 às 08:30 no Laboratório Joaquim Chaves Saúde.
    Instruções: Jejum de 8 a 12 horas.
    """
    resultado = extrair_marcacao_saude(texto)
    assert resultado is not None
    assert resultado.tipo == "exame"
    assert resultado.nome_paciente == "aa-stop-run"
    assert "Análises de Sangue" in resultado.especialidade
    assert "Jejum" in resultado.preparacao_instrucoes
