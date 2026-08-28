import pytest
from hub.services.conversation_memory import ConversationMemoryManager


def test_conversation_memory_turn_limit():
    mgr = ConversationMemoryManager()
    ctx = mgr.get_session("test_sess")

    # Add 7 turnos (limite é 5)
    for i in range(7):
        ctx.add_turn(f"Query {i}", f"Response {i}", {"indice": i})

    assert len(ctx.turns) == 5
    assert ctx.turns[0].user_query == "Query 2"
    assert ctx.turns[-1].user_query == "Query 6"


def test_conversation_memory_entity_inheritance():
    mgr = ConversationMemoryManager()
    ctx = mgr.get_session("test_entities")

    # Turno 1: Utilizador pergunta por agosto de 2026
    ctx.add_turn("Quanto gastei em tabaco em agosto de 2026?", "Gastaste 110€", {"mes": 8, "ano": 2026, "veiculo": "Sedan 2.0 TDI"})

    # Turno 2: Pergunta sem data deve herdar as entidades ativas
    assert ctx.get_inherited_entity("mes") == 8
    assert ctx.get_inherited_entity("ano") == 2026
    assert ctx.get_inherited_entity("veiculo") == "Sedan 2.0 TDI"


def test_conversation_memory_pending_actions():
    mgr = ConversationMemoryManager()
    
    # Criar ação pendente Nível 2
    action_data = {"type": "apagar_veiculo", "veiculo_id": "1234", "nome": "City Hatchback 1.2"}
    mgr.set_pending_action(action_data, session_id="test_act")

    ctx = mgr.get_session("test_act")
    assert ctx.pending_action == action_data

    # Pop da ação
    popped = mgr.pop_pending_action("test_act")
    assert popped == action_data
    assert ctx.pending_action is None
