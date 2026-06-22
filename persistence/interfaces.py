"""Persistence interfaces used by graph runtime and future workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from schemas.agent_state import AgentState
from schemas.event import AgentEvent
from schemas.memory import SimilarCase


@dataclass(frozen=True)
class ArtifactRecord:
    """Stored artifact metadata and content reference."""

    artifact_ref: str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactMetadataRecord:
    """Stored artifact metadata without artifact content."""

    artifact_id: str
    artifact_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)
    mime_type: str | None = None
    content_type: str | None = None


class CheckpointStore(Protocol):
    """Workflow state checkpoint storage contract."""

    def save_checkpoint(self, state: AgentState) -> None:
        """Persist a workflow state checkpoint."""

    def load_checkpoint(self, session_id: str, job_id: str) -> AgentState | None:
        """Load a workflow state checkpoint."""


class CacheStore(Protocol):
    """Key-value cache storage contract."""

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Store a value under a key."""

    def get(self, key: str) -> Any | None:
        """Return a cached value or None."""

    def delete(self, key: str) -> None:
        """Remove a cached value."""


class EventStore(Protocol):
    """Structured event storage contract."""

    def append_event(self, event: AgentEvent) -> None:
        """Append a structured event."""

    def list_events(
        self, session_id: str | None = None, job_id: str | None = None
    ) -> list[AgentEvent]:
        """List events, optionally filtered by session and job."""


class ArtifactStore(Protocol):
    """Artifact storage contract that returns references instead of inline files."""

    def save_artifact(self, content: Any, metadata: dict[str, Any] | None = None) -> str:
        """Persist artifact content and return an artifact reference."""

    def get_artifact(self, artifact_ref: str) -> ArtifactRecord | None:
        """Return an artifact record by reference."""

    def get_artifact_metadata(self, artifact_id_or_ref: str) -> ArtifactMetadataRecord | None:
        """Return artifact metadata by id or reference."""

    def get_artifact_content(self, artifact_id_or_ref: str) -> Any | None:
        """Return artifact content by id or reference."""


class VectorMemoryStore(Protocol):
    """Historical case storage contract for future similarity retrieval."""

    def add_case(self, case: SimilarCase) -> None:
        """Persist a historical analysis case."""

    def search_similar_cases(self, user_question: str, limit: int = 5) -> list[SimilarCase]:
        """Return candidate similar cases without embedding-specific assumptions."""
