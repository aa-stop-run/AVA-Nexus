import pytest
from datetime import datetime, date
from hub.services.agenda_service import obter_agenda_unificada


class MockSession:
    async def execute(self, statement, params=None):
        query_str = str(statement)
        
        class MockResult:
            def __init__(self, data):
                self._data = data
                
            def mappings(self):
                return self._data
                
            def scalar(self):
                return len(self._data)

        if "consulta_medica" in query_str:
            return MockResult([
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "data_hora": datetime(2026, 8, 28, 10, 30),
                    "especialidade": "Pediatria",
                    "medico": "Dra. Maria",
                    "local_clinica": "CUF Porto",
                    "paciente": "Junior",
                }
            ])
        elif "veiculo" in query_str:
            return MockResult([
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "nome": "Sedan 2.0 TDI",
                    "matricula": "AA-00-BB",
                    "data_proxima_ipo": date(2026, 8, 30),
                }
            ])
        elif "recorrente" in query_str:
            return MockResult([
                {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "descricao": "Mortgage & Loans",
                    "valor": 650.00,
                    "dia_do_mes": 28,
                    "categoria": "Habitação",
                }
            ])
        elif "evento_calendario" in query_str:
            return MockResult([
                {
                    "id": "44444444-4444-4444-4444-444444444444",
                    "titulo": "Jantar de Aniversário",
                    "descricao": "Restaurante Central",
                    "data_inicio": datetime(2026, 8, 29, 20, 0),
                    "data_fim": datetime(2026, 8, 29, 23, 0),
                    "tipo": "pessoal",
                    "local": "Porto",
                }
            ])
        return MockResult([])


@pytest.mark.asyncio
async def test_obter_agenda_unificada():
    session = MockSession()
    res = await obter_agenda_unificada(session, ano=2026, mes=8)
    
    assert res["ano"] == 2026
    assert res["mes"] == 8
    assert res["total_eventos"] >= 4
    
    tipos = [e["tipo"] for e in res["eventos"]]
    assert "saude" in tipos
    assert "veiculo" in tipos
    assert "financas" in tipos
    assert "pessoal" in tipos
    # Google calendar test se disponível
    assert any(t in tipos for t in ["saude", "veiculo", "financas"])
    
    # Verifica dots no mapa do mês
    assert "2026-08-28" in res["dias_com_eventos"]
    assert "rose" in res["dias_com_eventos"]["2026-08-28"]
    assert "cyan" in res["dias_com_eventos"]["2026-08-28"]
    assert "2026-08-29" in res["dias_com_eventos"]
    assert "2026-08-30" in res["dias_com_eventos"]


@pytest.mark.asyncio
async def test_obter_proximos_eventos():
    from hub.services.agenda_service import obter_proximos_eventos
    session = MockSession()
    res = await obter_proximos_eventos(session, limite=5, dias_a_frente=60)

    assert "eventos" in res
    assert "total_hoje" in res
    assert len(res["eventos"]) >= 2
    
    titulos = [e["titulo"] for e in res["eventos"]]
    assert any("Consulta: Pediatria" in t for t in titulos)
    assert any("Inspeção IPO" in t for t in titulos)


@pytest.mark.asyncio
async def test_remover_evento_calendario_saude():
    from hub.services.agenda_service import remover_evento_calendario
    
    exec_queries = []
    class DeleteMockSession:
        async def execute(self, stmt, params=None):
            exec_queries.append((str(stmt), params))
            class DelResult:
                rowcount = 1
            return DelResult()
        async def commit(self):
            pass

    session = DeleteMockSession()
    # Teste 1: com prefixo saude-
    removido_saude = await remover_evento_calendario(session, "saude-dfe63031-1f5b-4993-b191-e1e35ac69eb8")
    assert removido_saude is True
    assert any("DELETE FROM consulta_medica" in q[0] for q in exec_queries)

    # Teste 2: evento pessoal (uuid direto)
    removido_evento = await remover_evento_calendario(session, "44444444-4444-4444-4444-444444444444")
    assert removido_evento is True
    assert any("DELETE FROM evento_calendario" in q[0] for q in exec_queries)


@pytest.mark.asyncio
async def test_atualizar_evento_calendario():
    from hub.services.agenda_service import atualizar_evento_calendario

    exec_queries = []
    class UpdateMockSession:
        async def execute(self, stmt, params=None):
            exec_queries.append((str(stmt), params))
            class UpResult:
                rowcount = 1
            return UpResult()
        async def commit(self):
            pass

    session = UpdateMockSession()
    # Atualizar evento pessoal
    res = await atualizar_evento_calendario(session, "44444444-4444-4444-4444-444444444444", {
        "titulo": "Novo Título",
        "local": "Novo Local"
    })
    assert res["status"] == "atualizado"
    assert any("UPDATE evento_calendario" in q[0] for q in exec_queries)

    # Atualizar consulta médica com prefixo saude-
    res_saude = await atualizar_evento_calendario(session, "saude-11111111-1111-1111-1111-111111111111", {
        "titulo": "Consulta: Dermatologia",
        "local": "CUF Cascais"
    })
    assert res_saude["status"] == "atualizado"
    assert any("UPDATE consulta_medica" in q[0] for q in exec_queries)



