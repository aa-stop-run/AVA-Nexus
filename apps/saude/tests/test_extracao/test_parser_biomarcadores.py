from decimal import Decimal
from saude.extracao.parser_biomarcadores import (
    extrair_biomarcadores,
    extrair_data_relatorio,
    extrair_laboratorio,
    extrair_titular_sugerido,
)


def test_extrair_biomarcadores_relatorio_joaquim_chaves():
    texto = """
    LABORATÓRIO JOAQUIM CHAVES SAÚDE
    Paciente: aa-stop-run
    Data de Colheita: 12/04/2026

    METABOLISMO
    Glicemia em jejum: 88 mg/dL (70 - 99)
    HbA1c: 5.2 % (4.0 - 5.6)

    LÍPIDOS
    Colesterol Total: 175 mg/dL (< 190)
    Colesterol HDL: 54 mg/dL (> 40)
    Colesterol LDL: 102 mg/dL (< 115)
    Triglicéridos: 95 mg/dL (< 150)

    VITAMINAS
    Vitamina D (25-OH): 34.5 ng/mL (30.0 - 100.0)
    Ferritina: 120 ng/mL (30 - 400)
    """

    data_rel = extrair_data_relatorio(texto)
    assert data_rel.year == 2026
    assert data_rel.month == 4
    assert data_rel.day == 12

    assert extrair_titular_sugerido(texto) == "aa-stop-run"
    assert "joaquim chaves" in extrair_laboratorio(texto).lower()

    biomarcadores = extrair_biomarcadores(texto)
    assert len(biomarcadores) >= 7

    glicemia = next(b for b in biomarcadores if b.parametro == "Glicémia")
    assert glicemia.valor == Decimal("88")
    assert glicemia.unidade == "mg/dL"

    ldl = next(b for b in biomarcadores if b.parametro == "Colesterol LDL")
    assert ldl.valor == Decimal("102")


def test_extrair_biomarcadores_unilabs():
    texto_unilabs = """
    Unilabs Campo Alegre
    Utente: aa-stop-run
    Data de Colheita 04-04-2024
    Data de Emissão 05-04-2024

    Hemoglobina (Hgb) 16.5 g/dL 13.2-16.6
    Eritrócitos 5.36 x10^12/L 4.35-5.65
    Leucócitos 6.670 x10^9/L 3.400-9.600
    Glicose 98 mg/dL 60-110
    Ureia 32 mg/dL 17-51
    Colesterol Total 214 mg/dL <200
    Colesterol HDL 50 mg/dL >60
    Colesterol LDL direto 133 mg/dL <130
    Triglicerídeos 157 mg/dL <150
    """

    data_rel = extrair_data_relatorio(texto_unilabs)
    assert data_rel.year == 2024
    assert data_rel.month == 4
    assert data_rel.day == 4

    assert extrair_titular_sugerido(texto_unilabs) == "aa-stop-run"
    assert len(extrair_laboratorio(texto_unilabs)) > 0

    biomarcadores = extrair_biomarcadores(texto_unilabs)
    leucocitos = next(b for b in biomarcadores if b.parametro == "Leucócitos")
    assert leucocitos.valor == Decimal("6.670")

    glicose = next(b for b in biomarcadores if b.parametro == "Glicémia")
    assert glicose.valor == Decimal("98")

    trig = next(b for b in biomarcadores if b.parametro == "Triglicéridos")
    assert trig.valor == Decimal("157")


def test_extrair_biomarcadores_germano_de_sousa():
    texto_germano = """
    GERMANO DE SOUSA - INSTITUTO CUF PORTO
    Utente: aa-stop-run
    Colheita: 29/07/2025
    Relatório: 30/07/2025

    Hemoglobina 16.4 g/dl 13.0 - 17.0 17.3
    Leucócitos 6.8 /µl 4.0 - 10.0 6.3
    Glicémia 109 mg/dL 70 - 110 103
    Uricémia 8.4 mg/dL 3.5 - 7.2
    Urémia 43 mg/dL < 50 33
    Creatininémia 1.10 mg/dL 0.70 - 1.30 1.13
    25-Hidroxivitamina D 20.60 ng/ml
    """

    data_rel = extrair_data_relatorio(texto_germano)
    assert data_rel.year == 2025
    assert data_rel.month == 7
    assert data_rel.day == 29

    assert extrair_titular_sugerido(texto_germano) == "aa-stop-run"
    assert len(extrair_laboratorio(texto_germano)) > 0

    biomarcadores = extrair_biomarcadores(texto_germano)
    leucocitos = next(b for b in biomarcadores if b.parametro == "Leucócitos")
    assert leucocitos.valor == Decimal("6.8")

    uricos = next(b for b in biomarcadores if "Ácido Úrico" in b.parametro)
    assert uricos.valor == Decimal("8.4")

    vit_d = next(b for b in biomarcadores if "Vitamina D" in b.parametro)
    assert vit_d.valor == Decimal("20.60")


def test_extrair_biomarcadores_charlie_pediatria():
    texto_charlie = """
    GERMANO DE SOUSA - INSTITUTO CUF PORTO
    Análises de Menino
    CHARLIE MORGAN
    Colheita: 04/10/2025
    Relatório: 04/10/2025
    Processo: JMS30363390

    Hemoglobina 14.8 g/dl 13.0 - 16.0
    Leucócitos 5.9 /µl 4.5 - 11.5
    Ferritina 28.8 ng/ml 30.0 - 340.0
    Siderémia 40 µg/dl 20 - 100
    Glicémia 93 mg/dL 70 - 110
    Urémia 32 mg/dL 19 - 45
    Creatininémia 0.67 ml/min/1,73 m2 0.70 - 1.30
    """

    assert extrair_titular_sugerido(texto_charlie) == "Junior"
    data_rel = extrair_data_relatorio(texto_charlie)
    assert data_rel.year == 2025
    assert data_rel.month == 10
    assert data_rel.day == 4

    biomarcadores = extrair_biomarcadores(texto_charlie)
    ferritina = next(b for b in biomarcadores if b.parametro == "Ferritina")
    assert ferritina.valor == Decimal("28.8")

    leucocitos = next(b for b in biomarcadores if b.parametro == "Leucócitos")
    assert leucocitos.valor == Decimal("5.9")

