import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ConversationTurn:
    user_query: str
    bot_response: str
    timestamp: float
    entities: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationContext:
    session_id: str
    turns: List[ConversationTurn] = field(default_factory=list)
    active_entities: Dict[str, Any] = field(default_factory=dict)
    pending_action: Optional[Dict[str, Any]] = None
    last_activity: float = field(default_factory=time.time)

    def is_expired(self, timeout_seconds: float = 300.0) -> bool:
        """Expira após 5 minutos de inatividade."""
        return (time.time() - self.last_activity) > timeout_seconds

    def add_turn(self, query: str, response: str, entities: Optional[Dict[str, Any]] = None):
        now = time.time()
        self.last_activity = now
        ents = entities or {}
        
        # Atualizar entidades ativas com as novas encontradas
        for k, v in ents.items():
            if v is not None:
                self.active_entities[k] = v

        turn = ConversationTurn(
            user_query=query,
            bot_response=response,
            timestamp=now,
            entities=ents,
        )
        self.turns.append(turn)
        # Manter apenas os últimos 5 turnos
        if len(self.turns) > 5:
            self.turns.pop(0)

    def get_inherited_entity(self, key: str) -> Optional[Any]:
        """Obtém entidade do turno anterior se não estiver expirada."""
        if self.is_expired():
            self.active_entities.clear()
            self.pending_action = None
            return None
        return self.active_entities.get(key)


class ConversationMemoryManager:
    """Gestor de memória de diálogo multi-turn em memória RAM do servidor."""

    def __init__(self):
        self._sessions: Dict[str, ConversationContext] = {}

    def get_session(self, session_id: str = "default") -> ConversationContext:
        ctx = self._sessions.get(session_id)
        if not ctx or ctx.is_expired():
            ctx = ConversationContext(session_id=session_id)
            self._sessions[session_id] = ctx
        return ctx

    def set_pending_action(self, action_data: Dict[str, Any], session_id: str = "default"):
        """Define uma ação que aguarda confirmação Nível 2 (ex: apagar viatura)."""
        ctx = self.get_session(session_id)
        ctx.pending_action = action_data
        ctx.last_activity = time.time()

    def pop_pending_action(self, session_id: str = "default") -> Optional[Dict[str, Any]]:
        """Retira a ação pendente após confirmação ou cancelamento."""
        ctx = self.get_session(session_id)
        act = ctx.pending_action
        ctx.pending_action = None
        return act


# Instância global do gestor de memória
conversation_memory = ConversationMemoryManager()
