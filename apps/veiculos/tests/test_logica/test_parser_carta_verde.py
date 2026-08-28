import pytest
from datetime import date
from veiculos.logica.parser_carta_verde import extrair_carta_verde


def test_extrair_carta_verde_divina():
    ocr_text = """
1. INTERNATIONAL MOTOR INSURANCE CARD
1. CARTE INTERNATIONALE D'ASSURANCE AUTOMOBILE
1. CERTIFICADO INTERNACIONAL DE SEGURO AUTOMÓVEL
2. EMITIDO COM A AUTORIÇÃO DO GABINETE
PORTUGUÉS DE CARTA VERDE
3. VÁLIDO 4. Código do País/ Código do Segurador / Número
DE A
(Estas datas estão incluidas)
5. Nº de Plate. Na falta desde, Nº do Chassis ou Nº do motor 6. Categoria do veículo(*) 7. Marca do veículo
02 06 2026
AA-01-BB
02 12 2026
P / 5085 / 142001304364
A RENAULT Mégane 1.4 Confort
DIA MÊS ANO DIA MÊS ANO
9. Nome e endereço do Tomador do Seguro (ou do utente do veículo)
ALEX MORGAN
10. Este certificado foi emitido por: Divina Pastora Seguros Generales, S.A.U.
Calle Xátiva 23, 46002 Valência - Espanha
Assistência em Viagem
(24h - 7dias/semana)
+351 309 739 806
Número Segurnet: AVV1Q9SA1G
Rua FONTE DO LINHAR, 310 / 4435-702 - Baguim do Monte
Em caso de quebra de Vidro:
Nº Azul: 808 211 690
Telefone Portugal: +351218704900
"""
    res = extrair_carta_verde(ocr_text)
    assert res is not None
    assert res.matricula == "AA-01-BB"
    assert res.seguradora == "Divina Seguros"
    assert res.numero_apolice == "142001304364"
    assert res.codigo_pais_segurador_numero == "P / 5085 / 142001304364"
    assert res.numero_segurnet == "AVV1Q9SA1G"
    assert res.data_inicio == date(2026, 6, 2)
    assert res.data_fim == date(2026, 12, 2)
    assert "RENAULT" in (res.marca_modelo or "")
    assert "ALEX" in (res.tomador_nome or "")
    assert "309 739 806" in (res.assistencia_viagem or "")
    assert "808 211 690" in (res.quebra_vidros or "")
