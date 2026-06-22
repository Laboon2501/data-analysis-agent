"""In-memory checkpoint store for tests and local runtime wiring."""

from __future__ import annotations

from schemas.agent_state import AgentState


class InMemoryCheckpointStore:
    """Process-local checkpoint store keyed by session and job."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], AgentState] = {}

    def save_checkpoint(self, state: AgentState) -> None:
        """Save a deep copy of workflow state."""

        self._states[(state.session_id, state.job_id)] = state.model_copy(deep=True)

    def load_checkpoint(self, session_id: str, job_id: str) -> AgentState | None:
        """Load a deep copy of workflow state if present."""

        state = self._states.get((session_id, job_id))
        return None if state is None else state.model_copy(deep=True)
