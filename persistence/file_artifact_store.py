"""Filesystem-backed ArtifactStore implementation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from persistence.interfaces import ArtifactMetadataRecord, ArtifactRecord

ARTIFACT_DIR_ENV = "DATA_ANALYSIS_AGENT_ARTIFACT_DIR"
DEFAULT_ARTIFACT_DIR = "artifacts"


class FileArtifactStore:
    """Local filesystem artifact store with JSON metadata sidecars."""

    def __init__(self, *, root_dir: str | Path | None = None) -> None:
        configured_root = root_dir or os.getenv(ARTIFACT_DIR_ENV, DEFAULT_ARTIFACT_DIR)
        self.root_dir = Path(configured_root).resolve()

    @classmethod
    def from_env(cls) -> FileArtifactStore:
        """Build a file artifact store using environment configuration."""

        return cls()

    def save_artifact(self, content: Any, metadata: dict[str, Any] | None = None) -> str:
        """Persist artifact content locally and return an opaque reference."""

        artifact_id = str(uuid4())
        self.root_dir.mkdir(parents=True, exist_ok=True)
        content_path = self._artifact_content_path(artifact_id, content)
        metadata_path = self._artifact_metadata_path(artifact_id)
        self._write_content(content_path, content)
        metadata_payload = {
            "artifact_id": artifact_id,
            "artifact_ref": self._artifact_ref(artifact_id),
            "content_path": str(content_path),
            "content_type": _content_type(content),
            "metadata": metadata or {},
        }
        metadata_path.write_text(
            json.dumps(metadata_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return self._artifact_ref(artifact_id)

    def get_artifact(self, artifact_ref: str) -> ArtifactRecord | None:
        """Return an artifact record when metadata and content still exist."""

        artifact_id = self._artifact_id_from_ref(artifact_ref)
        metadata_path = self._artifact_metadata_path(artifact_id)
        if not metadata_path.exists():
            return None
        metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        content_path = self._resolve_inside_root(metadata_payload["content_path"])
        if not content_path.exists():
            return None
        return ArtifactRecord(
            artifact_ref=artifact_ref,
            content=self._read_content(content_path, metadata_payload.get("content_type")),
            metadata=metadata_payload.get("metadata", {}),
        )

    def get_artifact_metadata(self, artifact_id_or_ref: str) -> ArtifactMetadataRecord | None:
        """Return artifact metadata without reading or returning content."""

        artifact_id = self._artifact_id_from_ref(artifact_id_or_ref)
        metadata_path = self._artifact_metadata_path(artifact_id)
        if not metadata_path.exists():
            return None
        metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata = metadata_payload.get("metadata", {})
        return ArtifactMetadataRecord(
            artifact_id=artifact_id,
            artifact_ref=metadata_payload["artifact_ref"],
            metadata=metadata,
            mime_type=_mime_type_from_metadata(metadata),
            content_type=metadata_payload.get("content_type"),
        )

    def get_artifact_content(self, artifact_id_or_ref: str) -> Any | None:
        """Return artifact content by id or reference."""

        record = self.get_artifact(artifact_id_or_ref)
        return None if record is None else record.content

    def _artifact_content_path(self, artifact_id: str, content: Any) -> Path:
        """Return the local content file path for one artifact."""

        return self._resolve_inside_root(f"{artifact_id}{_file_extension(content)}")

    def _artifact_metadata_path(self, artifact_id: str) -> Path:
        """Return the local metadata sidecar path for one artifact."""

        return self._resolve_inside_root(f"{artifact_id}.metadata.json")

    @staticmethod
    def _artifact_ref(artifact_id: str) -> str:
        """Return an opaque artifact reference."""

        return f"artifact:file:{artifact_id}"

    @staticmethod
    def _artifact_id_from_ref(artifact_ref: str) -> str:
        """Extract artifact id from a file artifact reference."""

        prefix = "artifact:file:"
        if not artifact_ref.startswith("artifact:"):
            artifact_id = artifact_ref
        elif artifact_ref.startswith(prefix):
            artifact_id = artifact_ref.removeprefix(prefix)
        else:
            raise ValueError(f"Unsupported file artifact ref: {artifact_ref}")
        if "/" in artifact_id or "\\" in artifact_id or artifact_id in {"", ".", ".."}:
            raise ValueError(f"Invalid artifact id in ref: {artifact_ref}")
        return artifact_id

    def _resolve_inside_root(self, path: str | Path) -> Path:
        """Resolve a path and ensure it stays under the artifact root."""

        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root_dir / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root_dir):
            raise ValueError(f"Artifact path escapes root directory: {path}")
        return resolved

    @staticmethod
    def _write_content(path: Path, content: Any) -> None:
        """Write artifact content using a simple type-based encoding."""

        if isinstance(content, bytes):
            path.write_bytes(content)
            return
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
            return
        path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _read_content(path: Path, content_type: str | None) -> Any:
        """Read artifact content using stored content type metadata."""

        if content_type == "bytes":
            return path.read_bytes()
        if content_type == "json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")


def _content_type(content: Any) -> str:
    """Return a stable content type label for metadata."""

    if isinstance(content, bytes):
        return "bytes"
    if isinstance(content, str):
        return "text"
    return "json"


def _file_extension(content: Any) -> str:
    """Return a storage extension based on content type."""

    if isinstance(content, bytes):
        return ".bin"
    if isinstance(content, str):
        return ".txt"
    return ".json"


def _mime_type_from_metadata(metadata: dict[str, Any]) -> str | None:
    """Return mime type from artifact metadata when present."""

    mime_type = metadata.get("mime_type")
    return str(mime_type) if mime_type is not None else None
