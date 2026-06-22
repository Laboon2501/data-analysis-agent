"""Memory nodes for retrieving historical analysis cases."""

from __future__ import annotations

from persistence.interfaces import VectorMemoryStore
from schemas.agent_state import AgentState


def retrieve_similar_cases(
    state: AgentState,
    *,
    memory_store: VectorMemoryStore | None = None,
    limit: int = 5,
) -> AgentState:
    """Retrieve similar cases when a memory store is available."""

    if memory_store is None:
        state.similar_cases = []
        return state
    state.similar_cases = memory_store.search_similar_cases(state.user_message, limit=limit)
    return state
