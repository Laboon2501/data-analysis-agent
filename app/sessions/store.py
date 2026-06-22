"""In-memory user-visible session history store."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from uuid import uuid4

from app.llm_runtime import LLMRuntimeMode
from app.sessions.base import (
    ChatMessage,
    ChatRole,
    SessionCleanupResult,
    SessionJobSummary,
    SessionRecord,
    SessionStore,
    SessionStoreStatus,
    SessionTitleSource,
    default_title,
    merge_artifact_refs,
    normalize_artifact_ref,
    preview_content,
    sanitize_session_title,
    title_from_first_user_message,
)
from schemas._base import utc_now
from schemas.context_summary import AgentContextSummary


class InMemorySessionStore(SessionStore):
    """Process-local session history store for tests and default local API runs."""

    def __init__(
        self,
        *,
        ttl_days: int | None = None,
        max_messages: int | None = None,
    ) -> None:
        self.ttl_days = ttl_days
        self.max_messages = max_messages
        self._sessions: dict[str, SessionRecord] = {}
        self._messages_by_session: dict[str, list[ChatMessage]] = {}
        self._jobs_by_session: dict[str, dict[str, SessionJobSummary]] = {}

    def create_session(
        self,
        *,
        session_id: str | None = None,
        title: str | None = None,
    ) -> SessionRecord:
        """Create a session; return the existing record when it already exists."""

        active_session_id = session_id or str(uuid4())
        if active_session_id in self._sessions:
            return self._sessions[active_session_id].model_copy(deep=True)
        now = utc_now()
        record = SessionRecord(
            session_id=active_session_id,
            title=title or default_title(active_session_id),
            created_at=now,
            updated_at=now,
        )
        self._sessions[active_session_id] = record
        self._messages_by_session.setdefault(active_session_id, [])
        self._jobs_by_session.setdefault(active_session_id, {})
        return record.model_copy(deep=True)

    def ensure_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
    ) -> SessionRecord:
        """Read or create a session."""

        if session_id not in self._sessions:
            return self.create_session(session_id=session_id, title=title)
        return self._sessions[session_id].model_copy(deep=True)

    def list_sessions(self) -> list[SessionRecord]:
        """Return sessions in most-recent-first order."""

        return [
            session.model_copy(deep=True)
            for session in sorted(
                self._sessions.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
        ]

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Read one session."""

        record = self._sessions.get(session_id)
        return None if record is None else record.model_copy(deep=True)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its visible messages/job summaries."""

        existed = session_id in self._sessions
        self._sessions.pop(session_id, None)
        self._messages_by_session.pop(session_id, None)
        self._jobs_by_session.pop(session_id, None)
        return existed

    def add_message(
        self,
        session_id: str,
        *,
        role: ChatRole,
        content: str,
        job_id: str | None = None,
        artifact_refs: Iterable[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatMessage:
        """Append a message and update the session summary."""

        self.ensure_session(session_id)
        clean_refs = merge_artifact_refs([], artifact_refs or [])
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            job_id=job_id,
            artifact_refs=clean_refs,
            metadata=metadata or {},
        )
        self._messages_by_session.setdefault(session_id, []).append(message)
        self._trim_messages(session_id, self.max_messages)
        generated_title = title_from_first_user_message(
            self._sessions[session_id],
            role=role,
            content=content,
        )
        self._touch_session(
            session_id,
            last_message_preview=preview_content(content),
            artifact_refs=clean_refs,
            title=generated_title,
            title_source=SessionTitleSource.RULE if generated_title else None,
            summary=preview_content(content) if generated_title else None,
        )
        return message.model_copy(deep=True)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        """Return visible chat messages."""

        self.ensure_session(session_id)
        return [
            message.model_copy(deep=True)
            for message in self._messages_by_session.get(session_id, [])
        ]

    def record_job(self, summary: SessionJobSummary) -> SessionJobSummary:
        """Insert or update a job summary and merge artifact refs into the session."""

        self.ensure_session(summary.session_id)
        normalized_summary = summary.model_copy(
            update={"artifact_refs": merge_artifact_refs([], summary.artifact_refs)},
            deep=True,
        )
        self._jobs_by_session.setdefault(summary.session_id, {})[summary.job_id] = (
            normalized_summary
        )
        self._touch_session(
            summary.session_id,
            artifact_refs=normalized_summary.artifact_refs,
            updated_at=summary.updated_at,
            latest_context=_latest_context_from_summary(normalized_summary),
        )
        return normalized_summary.model_copy(deep=True)

    def list_jobs(self, session_id: str) -> list[SessionJobSummary]:
        """Return job summaries in most-recent-first order."""

        self.ensure_session(session_id)
        return [
            job.model_copy(deep=True)
            for job in sorted(
                self._jobs_by_session.get(session_id, {}).values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
        ]

    def rename_session(
        self,
        session_id: str,
        *,
        title: str,
        title_source: SessionTitleSource = SessionTitleSource.USER,
        summary: str | None = None,
    ) -> SessionRecord:
        """Rename a session using a product-facing title."""

        self.ensure_session(session_id)
        clean_title = sanitize_session_title(title)
        if not clean_title:
            raise ValueError("Session title cannot be empty.")
        self._touch_session(
            session_id,
            title=clean_title,
            title_source=title_source,
            summary=summary,
        )
        return self._sessions[session_id].model_copy(deep=True)

    def update_session_datasource(
        self,
        session_id: str,
        datasource_id: str | None,
    ) -> SessionRecord:
        """Update a session datasource selection."""

        self.ensure_session(session_id)
        self._touch_session(session_id, datasource_id=datasource_id)
        return self._sessions[session_id].model_copy(deep=True)

    def set_datasource(self, session_id: str, datasource_id: str | None) -> SessionRecord:
        """Backward-compatible alias for older callers."""

        return self.update_session_datasource(session_id, datasource_id)

    def update_session_llm_config(
        self,
        session_id: str,
        *,
        mode: LLMRuntimeMode,
        enabled_nodes: Iterable[str],
    ) -> SessionRecord:
        """Update a session LLM rollout summary."""

        self.ensure_session(session_id)
        self._touch_session(
            session_id,
            llm_mode=mode,
            enabled_llm_nodes=list(dict.fromkeys(enabled_nodes)),
        )
        return self._sessions[session_id].model_copy(deep=True)

    def set_llm_config(
        self,
        session_id: str,
        *,
        mode: LLMRuntimeMode,
        enabled_nodes: Iterable[str],
    ) -> SessionRecord:
        """Backward-compatible alias for older callers."""

        return self.update_session_llm_config(
            session_id,
            mode=mode,
            enabled_nodes=enabled_nodes,
        )

    def add_artifact_ref(self, session_id: str, artifact_ref: str) -> SessionRecord:
        """Attach one artifact ref to a session without reading artifact content."""

        self.ensure_session(session_id)
        self._touch_session(session_id, artifact_refs=[normalize_artifact_ref(artifact_ref)])
        return self._sessions[session_id].model_copy(deep=True)

    def update_context_summary(
        self,
        session_id: str,
        context_summary: AgentContextSummary | None,
    ) -> SessionRecord:
        """Persist a compact workflow context summary for one session."""

        self.ensure_session(session_id)
        self._touch_session(session_id, context_summary=context_summary)
        return self._sessions[session_id].model_copy(deep=True)

    def cleanup_expired_sessions(
        self,
        *,
        ttl_days: int | None = None,
        max_messages: int | None = None,
        exclude_session_ids: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> SessionCleanupResult:
        """Delete expired sessions and trim old messages."""

        active_ttl_days = ttl_days if ttl_days is not None else self.ttl_days
        active_max_messages = max_messages if max_messages is not None else self.max_messages
        excluded = set(exclude_session_ids or [])
        now_value = now or utc_now()
        deleted = 0
        trimmed = 0

        if active_ttl_days is not None and active_ttl_days >= 0:
            cutoff = now_value - timedelta(days=active_ttl_days)
            for session_id, record in list(self._sessions.items()):
                if session_id in excluded:
                    continue
                if record.updated_at < cutoff:
                    self.delete_session(session_id)
                    deleted += 1

        for session_id in list(self._sessions):
            trimmed += self._trim_messages(session_id, active_max_messages)
            self._touch_session(session_id)

        return SessionCleanupResult(
            deleted_sessions=deleted,
            trimmed_messages=trimmed,
            remaining_sessions=len(self._sessions),
        )

    def status(self) -> SessionStoreStatus:
        """Return safe runtime status for health endpoints."""

        return SessionStoreStatus(
            store_type="memory",
            persistent=False,
            ttl_days=self.ttl_days,
            max_messages=self.max_messages,
            session_count=len(self._sessions),
        )

    def _touch_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        datasource_id: str | None = None,
        llm_mode: LLMRuntimeMode | None = None,
        enabled_llm_nodes: list[str] | None = None,
        last_message_preview: str | None = None,
        artifact_refs: Iterable[str] | None = None,
        updated_at: datetime | None = None,
        title_source: SessionTitleSource | None = None,
        summary: str | None = None,
        latest_context: dict[str, object] | None = None,
        context_summary: AgentContextSummary | None = None,
    ) -> None:
        """Update one SessionRecord in a single place."""

        current = self._sessions[session_id]
        messages = self._messages_by_session.get(session_id, [])
        context_updates = latest_context or {}
        self._sessions[session_id] = current.model_copy(
            update={
                "title": title or current.title,
                "summary": summary if summary is not None else current.summary,
                "title_source": title_source or current.title_source,
                "updated_at": updated_at or utc_now(),
                "datasource_id": (
                    datasource_id if datasource_id is not None else current.datasource_id
                ),
                "llm_mode": llm_mode or current.llm_mode,
                "enabled_llm_nodes": (
                    enabled_llm_nodes
                    if enabled_llm_nodes is not None
                    else current.enabled_llm_nodes
                ),
                "message_count": len(messages),
                "last_message_preview": last_message_preview or current.last_message_preview,
                "artifact_refs": merge_artifact_refs(
                    current.artifact_refs,
                    artifact_refs or [],
                ),
                "context_summary": (
                    context_summary if context_summary is not None else current.context_summary
                ),
                **context_updates,
            },
            deep=True,
        )

    def _trim_messages(self, session_id: str, max_messages: int | None) -> int:
        """Keep only the newest max_messages entries for a session."""

        if max_messages is None or max_messages < 0:
            return 0
        messages = self._messages_by_session.get(session_id, [])
        overflow = max(0, len(messages) - max_messages)
        if overflow <= 0:
            return 0
        del messages[:overflow]
        return overflow


def _latest_context_from_summary(summary: SessionJobSummary) -> dict[str, object]:
    """Extract bounded latest-context references from one job summary."""

    updates: dict[str, object] = {}
    if summary.analysis_package_id:
        updates["latest_analysis_package_id"] = summary.analysis_package_id
        updates["latest_exportable_job_id"] = summary.job_id
    if summary.report_outline_id:
        updates["latest_report_outline_id"] = summary.report_outline_id
        updates["latest_exportable_job_id"] = summary.job_id
    for field_name, session_field in (
        ("report_artifact_ref", "latest_report_artifact_ref"),
        ("dashboard_artifact_ref", "latest_dashboard_artifact_ref"),
        ("excel_artifact_ref", "latest_excel_artifact_ref"),
        ("ppt_artifact_ref", "latest_ppt_artifact_ref"),
    ):
        value = getattr(summary, field_name)
        if value:
            updates[session_field] = normalize_artifact_ref(value)
            updates["latest_exportable_job_id"] = summary.job_id
    return updates
