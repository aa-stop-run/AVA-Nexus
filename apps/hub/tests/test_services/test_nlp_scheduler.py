import pytest
from datetime import date, datetime, timezone
from hub.services.nlp_scheduler import (
    extrair_data_hora,
    extrair_entidades_consulta,
    extrair_entidades_evento,
    tentar_agendar_por_texto,
)


def test_extrair_data_hora_relativo():
    base = date(2026, 8, 26)
    dt_amanha = extrair_data_hora("marca para amanhã às 10h30", data_base=base)
    assert dt_amanha is not None
    assert dt_amanha.day == 27
    assert dt_amanha.month == 8
    assert dt_amanha.year == 2026
    assert dt_amanha.hour == 10
    assert dt_amanha.minute == 30


def test_extrair_data_hora_extenso():
    base = date(2026, 8, 26)
    dt = extrair_data_hora("dia 15 de setembro às 14:00", data_base=base)
    assert dt is not None
    assert dt.day == 15
    assert dt.month == 9
    assert dt.year == 2026
    assert dt.hour == 14
    assert dt.minute == 0


def test_extrair_data_hora_numerico():
    base = date(2026, 8, 26)
    dt = extrair_data_hora("28/08/2026 às 20h", data_base=base)
    assert dt is not None
    assert dt.day == 28
    assert dt.month == 8
    assert dt.year == 2026
    assert dt.hour == 20
    assert dt.minute == 0


def test_extrair_entidades_consulta_completa():
    texto = "marca consulta de pediatria para o Junior no dia 15 de setembro às 10:30 na CUF com a Dra. Sofia"
    ent = extrair_entidades_consulta(texto)
    assert ent is not None
    assert ent["tipo"] == "saude"
    assert ent["paciente"] == "Junior"
    assert ent["especialidade"] == "Pediatria"
    assert "CUF" in ent["local_clinica"]
    assert "Sofia" in ent["medico"]
    assert ent["data_hora"].day == 15
    assert ent["data_hora"].month == 9
    assert ent["data_hora"].hour == 10
    assert ent["data_hora"].minute == 30


def test_extrair_entidades_consulta_sam():
    texto = "agendar dentista para a Member dia 2 de outubro às 15h na clínica Santa Maria"
    ent = extrair_entidades_consulta(texto)
    assert ent is not None
    assert ent["paciente"] == "Member"
    assert ent["especialidade"] == "Dentista"
    assert ent["data_hora"].day == 2
    assert ent["data_hora"].month == 10
    assert ent["data_hora"].hour == 15


def test_extrair_entidades_evento_jantar():
    texto = "agenda jantar de anos em família dia 28 de agosto às 20h no restaurante O Fuso"
    ent = extrair_entidades_evento(texto)
    assert ent is not None
    assert ent["tipo"] == "pessoal"
    assert "Jantar" in ent["titulo"]
    assert ent["data_hora"].day == 28
    assert ent["data_hora"].month == 8
    assert ent["data_hora"].hour == 20
    assert "Fuso" in ent["local"]


@pytest.mark.asyncio
async def test_tentar_agendar_ignora_perguntas_normais():
    class DummySession:
        pass

    res = await tentar_agendar_por_texto("quanto gastei em eletricidade?", DummySession())
    assert res is None

    res2 = await tentar_agendar_por_texto("o que tenho na agenda para hoje?", DummySession())
    assert res2 is None


@pytest.mark.asyncio
async def test_tentar_agendar_consulta_executa_insert():
    queries_executadas = []

    class MockResult:
        def mappings(self):
            class MockRowList(list):
                def first(self):
                    return {"perfil_id": "03d481b1-a47d-4431-be1d-f1659ff4fd87", "nome": "Junior"}
            return MockRowList([{"perfil_id": "03d481b1-a47d-4431-be1d-f1659ff4fd87", "nome": "Junior"}])

    class MockSession:
        async def execute(self, stmt, params=None):
            queries_executadas.append((str(stmt), params))
            return MockResult()
        async def commit(self):
            pass

    msg = await tentar_agendar_por_texto(
        "marca consulta de pediatria para o Junior no dia 15 de setembro às 10:30 na CUF com a Dra. Sofia",
        MockSession()
    )
    assert msg is not None
    assert "Marquei a consulta de **Pediatria** para o **Junior**" in msg
    assert "15 de Setembro" in msg or "15 de setembro" in msg
    assert "10:30" in msg
    assert "CUF" in msg
    assert "Dra. Sofia" in msg

    # Verificar que inseriu em consulta_medica
    insert_calls = [q for q in queries_executadas if "INSERT INTO consulta_medica" in q[0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    assert params["especialidade"] == "Pediatria"
    assert params["medico"] == "Dra. Sofia"
    assert "CUF" in params["local_clinica"]


@pytest.mark.asyncio
async def test_tentar_agendar_evento_executa_insert():
    queries_executadas = []

    class MockSession:
        async def execute(self, stmt, params=None):
            queries_executadas.append((str(stmt), params))
            return None
        async def commit(self):
            pass

    msg = await tentar_agendar_por_texto(
        "agenda jantar de aniversário em família dia 28 de agosto às 20h no restaurante O Fuso",
        MockSession()
    )
    assert msg is not None
    assert "Agendei **Jantar de aniversário em família**" in msg or "Jantar" in msg
    assert "28 de Agosto" in msg or "28 de agosto" in msg
    assert "20:00" in msg

    insert_calls = [q for q in queries_executadas if "INSERT INTO evento_calendario" in q[0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    assert "Jantar" in params["titulo"]
    assert "Fuso" in params["local"]

