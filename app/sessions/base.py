"""Shared session history models, helpers, and store protocol."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field

from app.llm_runtime import LLMRuntimeMode
from schemas._base import StrictBaseModel, utc_now
from schemas.context_summary import AgentContextSummary

ARTIFACT_REF_KEYS = frozenset({"artifact_ref", "chart_artifact_ref"})
ARTIFACT_REF_LIST_KEYS = frozenset({"artifact_refs", "chart_artifact_refs"})
ARTIFACT_ID_KEYS = frozenset({"artifact_id", "chart_artifact_id"})
MAX_PREVIEW_LENGTH = 160
MAX_TITLE_CHARS = 40
MAX_CJK_TITLE_CHARS = 20


class SessionTitleSource(StrEnum):
    """Source of a user-visible session title."""

    LLM = "llm"
    RULE = "rule"
    USER = "user"


class ChatRole(StrEnum):
    """Role names allowed in user-visible chat history."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(StrictBaseModel):
    """One user-visible chat message without artifact body content."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime = Field(default_factory=utc_now)
    job_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionJobSummary(StrictBaseModel):
    """Compact job summary shown in a session history view."""

    job_id: str
    session_id: str
    status: str
    intent: str
    command: str
    created_at: datetime
    updated_at: datetime
    final_response_text: str | None = None
    error_message: str | None = None
    needs_human: bool = False
    artifact_refs: list[str] = Field(default_factory=list)
    analysis_package_id: str | None = None
    report_outline_id: str | None = None
    report_artifact_ref: str | None = None
    dashboard_artifact_ref: str | None = None
    excel_artifact_ref: str | None = None
    ppt_artifact_ref: str | None = None


class SessionRecord(StrictBaseModel):
    """Lightweight session list record."""

    session_id: str
    title: str
    summary: str | None = None
    title_source: SessionTitleSource = SessionTitleSource.RULE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    datasource_id: str | None = None
    llm_mode: LLMRuntimeMode = LLMRuntimeMode.RULE
    enabled_llm_nodes: list[str] = Field(default_factory=list)
    message_count: int = 0
    last_message_preview: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    latest_analysis_package_id: str | None = None
    latest_report_outline_id: str | None = None
    latest_report_artifact_ref: str | None = None
    latest_dashboard_artifact_ref: str | None = None
    latest_excel_artifact_ref: str | None = None
    latest_ppt_artifact_ref: str | None = None
    latest_exportable_job_id: str | None = None
    context_summary: AgentContextSummary | None = None


class SessionCleanupResult(StrictBaseModel):
    """Result returned after manual session history cleanup."""

    deleted_sessions: int = 0
    trimmed_messages: int = 0
    remaining_sessions: int = 0


class SessionStoreStatus(StrictBaseModel):
    """Safe runtime metadata for a SessionStore implementation."""

    store_type: str
    persistent: bool = False
    db_url_masked: str | None = None
    ttl_days: int | None = None
    max_messages: int | None = None
    session_count: int = 0


class SessionStore(Protocol):
    """Replaceable user-visible session history store."""

    def create_session(
        self,
        *,
        session_id: str | None = None,
        title: str | None = None,
    ) -> SessionRecord:
        """Create a session or return the existing record."""

    def ensure_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
    ) -> SessionRecord:
        """Read or create a session."""

    def list_sessions(self) -> list[SessionRecord]:
        """Return sessions in most-recent-first order."""

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Read one session."""

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its visible history."""

    def add_message(
        self,
        session_id: str,
        *,
        role: ChatRole,
        content: str,
        job_id: str | None = None,
        artifact_refs: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """Append one visible chat message."""

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        """Return visible chat messages for a session."""

    def record_job(self, summary: SessionJobSummary) -> SessionJobSummary:
        """Insert or update one job summary."""

    def list_jobs(self, session_id: str) -> list[SessionJobSummary]:
        """Return compact job summaries for a session."""

    def rename_session(
        self,
        session_id: str,
        *,
        title: str,
        title_source: SessionTitleSource = SessionTitleSource.USER,
        summary: str | None = None,
    ) -> SessionRecord:
        """Rename a session without changing workflow state."""

    def update_session_datasource(
        self,
        session_id: str,
        datasource_id: str | None,
    ) -> SessionRecord:
        """Update the datasource selection summary."""

    def update_session_llm_config(
        self,
        session_id: str,
        *,
        mode: LLMRuntimeMode,
        enabled_nodes: Iterable[str],
    ) -> SessionRecord:
        """Update the session LLM rollout summary."""

    def add_artifact_ref(self, session_id: str, artifact_ref: str) -> SessionRecord:
        """Attach one artifact reference to the session record."""

    def update_context_summary(
        self,
        session_id: str,
        context_summary: AgentContextSummary | None,
    ) -> SessionRecord:
        """Persist the compact workflow context for this session."""

    def cleanup_expired_sessions(
        self,
        *,
        ttl_days: int | None = None,
        max_messages: int | None = None,
        exclude_session_ids: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> SessionCleanupResult:
        """Delete expired sessions and trim old messages."""

    def status(self) -> SessionStoreStatus:
        """Return safe implementation status for health endpoints."""


def extract_artifact_refs(value: Any) -> list[str]:
    """Extract artifact refs from structured data without reading artifact bodies."""

    refs: list[str] = []
    _visit_for_artifacts(value, refs)
    return merge_artifact_refs([], refs)


def merge_artifact_refs(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    """Normalize and deduplicate artifact refs while preserving order."""

    refs: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        normalized = normalize_artifact_ref(value)
        if not normalized or normalized in seen:
            continue
        refs.append(normalized)
        seen.add(normalized)
    return refs


def normalize_artifact_ref(value: str) -> str:
    """Normalize an artifact id or ref to artifact:<id>."""

    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    artifact_id = raw_value.split(":")[-1]
    return f"artifact:{artifact_id}"


def preview_content(content: str) -> str:
    """Build a one-line preview for session lists."""

    one_line = " ".join(str(content).split())
    if len(one_line) <= MAX_PREVIEW_LENGTH:
        return one_line
    return f"{one_line[:MAX_PREVIEW_LENGTH]}..."


def default_title(_session_id: str) -> str:
    """Return the default product-facing title for a new conversation."""

    return "新对话"


def sanitize_session_title(content: str) -> str:
    """Build a compact safe session title without secrets or artifact bodies."""

    clean = preview_content(_redact_secret_like_text(content)).strip(" '\"`.,;:，。；：")
    if not clean:
        return default_title("")
    max_chars = MAX_CJK_TITLE_CHARS if _contains_cjk(clean) else MAX_TITLE_CHARS
    return clean[:max_chars]


def title_from_first_user_message(
    record: SessionRecord,
    *,
    role: ChatRole,
    content: str,
) -> str | None:
    """Use the first user message as a friendlier default title."""

    if role is not ChatRole.USER:
        return None
    if record.title_source is SessionTitleSource.USER:
        return None
    if record.title != default_title(record.session_id):
        return None
    return sanitize_session_title(content) or None


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _redact_secret_like_text(value: str) -> str:
    return re.sub(
        r"(?i)(sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*\S+)",
        "[secret]",
        str(value),
    )


def _visit_for_artifacts(value: Any, refs: list[str]) -> None:
    """Recursively scan dict/list/Pydantic values for artifact reference fields."""

    if hasattr(value, "model_dump"):
        _visit_for_artifacts(value.model_dump(mode="json"), refs)
        return
    if isinstance(value, list | tuple):
        for item in value:
            _visit_for_artifacts(item, refs)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key in ARTIFACT_REF_KEYS and isinstance(item, str):
            refs.append(normalize_artifact_ref(item))
            continue
        if key in ARTIFACT_ID_KEYS and isinstance(item, str):
            refs.append(normalize_artifact_ref(item))
            continue
        if key in ARTIFACT_REF_LIST_KEYS and isinstance(item, list):
            refs.extend(normalize_artifact_ref(ref) for ref in item if isinstance(ref, str))
            continue
        _visit_for_artifacts(item, refs)
