"""In-memory artifact store that returns opaque references."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from persistence.interfaces import ArtifactMetadataRecord, ArtifactRecord


class InMemoryArtifactStore:
    """Process-local artifact store for tests."""

    def __init__(self) -> None:
        self._artifacts: dict[str, ArtifactRecord] = {}

    def save_artifact(self, content: Any, metadata: dict[str, Any] | None = None) -> str:
        """Save content and return an artifact reference."""

        artifact_ref = f"artifact:{uuid4()}"
        self._artifacts[artifact_ref] = ArtifactRecord(
            artifact_ref=artifact_ref,
            content=deepcopy(content),
            metadata=deepcopy(metadata or {}),
        )
        return artifact_ref

    def get_artifact(self, artifact_ref: str) -> ArtifactRecord | None:
        """Return a deep copy of an artifact record."""

        record = self._artifacts.get(_memory_artifact_ref(artifact_ref))
        return None if record is None else deepcopy(record)

    def get_artifact_metadata(self, artifact_id_or_ref: str) -> ArtifactMetadataRecord | None:
        """Return artifact metadata without content."""

        artifact_ref = _memory_artifact_ref(artifact_id_or_ref)
        record = self._artifacts.get(artifact_ref)
        if record is None:
            return None
        metadata = deepcopy(record.metadata)
        return ArtifactMetadataRecord(
            artifact_id=_artifact_id_from_ref(artifact_ref),
            artifact_ref=artifact_ref,
            metadata=metadata,
            mime_type=_mime_type_from_metadata(metadata),
            content_type=_content_type_from_content(record.content),
        )

    def get_artifact_content(self, artifact_id_or_ref: str) -> Any | None:
        """Return a deep copy of artifact content."""

        record = self.get_artifact(artifact_id_or_ref)
        return None if record is None else deepcopy(record.content)


def _memory_artifact_ref(artifact_id_or_ref: str) -> str:
    """Normalize an in-memory artifact id or reference to a full reference."""

    if artifact_id_or_ref.startswith("artifact:"):
        return artifact_id_or_ref
    return f"artifact:{artifact_id_or_ref}"


def _artifact_id_from_ref(artifact_ref: str) -> str:
    """Extract the final id segment from an artifact reference."""

    return artifact_ref.rsplit(":", maxsplit=1)[-1]


def _mime_type_from_metadata(metadata: dict[str, Any]) -> str | None:
    """Return mime type from artifact metadata when present."""

    mime_type = metadata.get("mime_type")
    return str(mime_type) if mime_type is not None else None


def _content_type_from_content(content: Any) -> str:
    """Return a coarse content type for API responses."""

    if isinstance(content, bytes):
        return "bytes"
    if isinstance(content, str):
        return "text"
    return "json"
