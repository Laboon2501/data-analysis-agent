"""SQLAlchemy-backed session history store."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine, make_url

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

_UNSET = object()


class SQLAlchemySessionStore(SessionStore):
    """Persist user-visible session history through SQLAlchemy Core tables."""

    def __init__(
        self,
        *,
        url: str,
        ttl_days: int | None = None,
        max_messages: int | None = None,
        create_schema: bool = True,
        engine: Engine | None = None,
    ) -> None:
        if not url:
            raise ValueError("SQLAlchemySessionStore requires a session database URL.")
        self.url = url
        self.ttl_days = ttl_days
        self.max_messages = max_messages
        self.engine = engine or create_engine(url, future=True)
        self.metadata = MetaData()
        self.sessions = Table(
            "session_records",
            self.metadata,
            Column("session_id", String(255), primary_key=True),
            Column("title", String(255), nullable=False),
            Column("summary", Text, nullable=True),
            Column("title_source", String(32), nullable=False, default="rule"),
            Column("created_at", String(64), nullable=False),
            Column("updated_at", String(64), nullable=False),
            Column("datasource_id", String(255), nullable=True),
            Column("llm_mode", String(64), nullable=False),
            Column("enabled_llm_nodes_json", Text, nullable=False),
            Column("message_count", Integer, nullable=False, default=0),
            Column("last_message_preview", Text, nullable=True),
            Column("artifact_refs_json", Text, nullable=False),
            Column("latest_analysis_package_id", String(255), nullable=True),
            Column("latest_report_outline_id", String(255), nullable=True),
            Column("latest_report_artifact_ref", String(255), nullable=True),
            Column("latest_dashboard_artifact_ref", String(255), nullable=True),
            Column("latest_excel_artifact_ref", String(255), nullable=True),
            Column("latest_ppt_artifact_ref", String(255), nullable=True),
            Column("latest_exportable_job_id", String(255), nullable=True),
            Column("context_summary_json", Text, nullable=True),
        )
        self.messages = Table(
            "session_messages",
            self.metadata,
            Column("message_id", String(255), primary_key=True),
            Column("session_id", String(255), index=True, nullable=False),
            Column("role", String(32), nullable=False),
            Column("content", Text, nullable=False),
            Column("created_at", String(64), nullable=False),
            Column("job_id", String(255), nullable=True),
            Column("artifact_refs_json", Text, nullable=False),
            Column("metadata_json", Text, nullable=False),
        )
        self.jobs = Table(
            "session_job_summaries",
            self.metadata,
            Column("job_id", String(255), primary_key=True),
            Column("session_id", String(255), index=True, nullable=False),
            Column("status", String(64), nullable=False),
            Column("intent", String(64), nullable=False),
            Column("command", String(64), nullable=False),
            Column("created_at", String(64), nullable=False),
            Column("updated_at", String(64), nullable=False),
            Column("final_response_text", Text, nullable=True),
            Column("error_message", Text, nullable=True),
            Column("needs_human", Boolean, nullable=False, default=False),
            Column("artifact_refs_json", Text, nullable=False),
            Column("analysis_package_id", String(255), nullable=True),
            Column("report_outline_id", String(255), nullable=True),
            Column("report_artifact_ref", String(255), nullable=True),
            Column("dashboard_artifact_ref", String(255), nullable=True),
            Column("excel_artifact_ref", String(255), nullable=True),
            Column("ppt_artifact_ref", String(255), nullable=True),
        )
        if create_schema:
            self.metadata.create_all(self.engine)
            self._ensure_compatible_schema()

    def create_session(
        self,
        *,
        session_id: str | None = None,
        title: str | None = None,
    ) -> SessionRecord:
        """Create a session or return the existing record."""

        active_session_id = session_id or str(uuid4())
        with self.engine.begin() as conn:
            existing = self._get_session_conn(conn, active_session_id)
            if existing is not None:
                return existing
            now = utc_now()
            record = SessionRecord(
                session_id=active_session_id,
                title=title or default_title(active_session_id),
                created_at=now,
                updated_at=now,
            )
            conn.execute(insert(self.sessions).values(**self._record_values(record)))
            return record.model_copy(deep=True)

    def ensure_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
    ) -> SessionRecord:
        """Read or create a session."""

        with self.engine.begin() as conn:
            existing = self._get_session_conn(conn, session_id)
            if existing is not None:
                return existing
        return self.create_session(session_id=session_id, title=title)

    def list_sessions(self) -> list[SessionRecord]:
        """Return sessions in most-recent-first order."""

        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.sessions).order_by(self.sessions.c.updated_at.desc())
            ).all()
        return [self._row_to_record(row._mapping) for row in rows]

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Read one session."""

        with self.engine.begin() as conn:
            return self._get_session_conn(conn, session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its visible history."""

        with self.engine.begin() as conn:
            existing = self._get_session_conn(conn, session_id)
            if existing is None:
                return False
            self._delete_session_conn(conn, session_id)
            return True

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
        """Append one message and enforce max_messages retention."""

        clean_refs = merge_artifact_refs([], artifact_refs or [])
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            job_id=job_id,
            artifact_refs=clean_refs,
            metadata=metadata or {},
        )
        with self.engine.begin() as conn:
            record = self._ensure_session_conn(conn, session_id)
            conn.execute(insert(self.messages).values(**self._message_values(message)))
            self._trim_messages_conn(conn, session_id, self.max_messages)
            generated_title = title_from_first_user_message(
                record,
                role=role,
                content=content,
            )
            self._touch_session_conn(
                conn,
                session_id,
                title=generated_title,
                title_source=SessionTitleSource.RULE if generated_title else None,
                summary=preview_content(content) if generated_title else None,
                last_message_preview=preview_content(content),
                artifact_refs=clean_refs,
            )
        return message.model_copy(deep=True)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        """Return visible messages for one session."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            rows = conn.execute(
                select(self.messages)
                .where(self.messages.c.session_id == session_id)
                .order_by(self.messages.c.created_at.asc())
            ).all()
        return [self._row_to_message(row._mapping) for row in rows]

    def record_job(self, summary: SessionJobSummary) -> SessionJobSummary:
        """Insert or update one compact job summary."""

        normalized_summary = summary.model_copy(
            update={"artifact_refs": merge_artifact_refs([], summary.artifact_refs)},
            deep=True,
        )
        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, summary.session_id)
            existing = conn.execute(
                select(self.jobs.c.job_id).where(self.jobs.c.job_id == summary.job_id)
            ).first()
            values = self._job_values(normalized_summary)
            if existing is None:
                conn.execute(insert(self.jobs).values(**values))
            else:
                conn.execute(
                    update(self.jobs).where(self.jobs.c.job_id == summary.job_id).values(**values)
                )
            self._touch_session_conn(
                conn,
                summary.session_id,
                artifact_refs=normalized_summary.artifact_refs,
                updated_at=summary.updated_at,
                latest_context=_latest_context_from_summary(normalized_summary),
            )
        return normalized_summary.model_copy(deep=True)

    def list_jobs(self, session_id: str) -> list[SessionJobSummary]:
        """Return compact job summaries in most-recent-first order."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            rows = conn.execute(
                select(self.jobs)
                .where(self.jobs.c.session_id == session_id)
                .order_by(self.jobs.c.updated_at.desc())
            ).all()
        return [self._row_to_job(row._mapping) for row in rows]

    def rename_session(
        self,
        session_id: str,
        *,
        title: str,
        title_source: SessionTitleSource = SessionTitleSource.USER,
        summary: str | None = None,
    ) -> SessionRecord:
        """Rename a session using a product-facing title."""

        clean_title = sanitize_session_title(title)
        if not clean_title:
            raise ValueError("Session title cannot be empty.")
        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            return self._touch_session_conn(
                conn,
                session_id,
                title=clean_title,
                title_source=title_source,
                summary=summary,
            )

    def update_session_datasource(
        self,
        session_id: str,
        datasource_id: str | None,
    ) -> SessionRecord:
        """Update datasource selection for one session."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            return self._touch_session_conn(conn, session_id, datasource_id=datasource_id)

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
        """Update LLM rollout summary for one session."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            return self._touch_session_conn(
                conn,
                session_id,
                llm_mode=mode,
                enabled_llm_nodes=list(dict.fromkeys(enabled_nodes)),
            )

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
        """Attach one artifact ref without reading artifact content."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            return self._touch_session_conn(
                conn,
                session_id,
                artifact_refs=[normalize_artifact_ref(artifact_ref)],
            )

    def update_context_summary(
        self,
        session_id: str,
        context_summary: AgentContextSummary | None,
    ) -> SessionRecord:
        """Persist a compact workflow context summary for one session."""

        with self.engine.begin() as conn:
            self._ensure_session_conn(conn, session_id)
            return self._touch_session_conn(
                conn,
                session_id,
                context_summary=context_summary,
            )

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
        with self.engine.begin() as conn:
            records = [
                self._row_to_record(row._mapping)
                for row in conn.execute(select(self.sessions)).all()
            ]
            if active_ttl_days is not None and active_ttl_days >= 0:
                cutoff = now_value - timedelta(days=active_ttl_days)
                for record in records:
                    if record.session_id in excluded:
                        continue
                    if record.updated_at < cutoff:
                        self._delete_session_conn(conn, record.session_id)
                        deleted += 1
            remaining_ids = [
                row._mapping["session_id"]
                for row in conn.execute(select(self.sessions.c.session_id)).all()
            ]
            for session_id in remaining_ids:
                trimmed += self._trim_messages_conn(
                    conn,
                    session_id,
                    active_max_messages,
                )
                self._touch_session_conn(conn, session_id)
            remaining_sessions = int(
                conn.execute(select(func.count()).select_from(self.sessions)).scalar_one()
            )
        return SessionCleanupResult(
            deleted_sessions=deleted,
            trimmed_messages=trimmed,
            remaining_sessions=remaining_sessions,
        )

    def status(self) -> SessionStoreStatus:
        """Return safe runtime metadata without exposing credentials."""

        with self.engine.begin() as conn:
            session_count = int(
                conn.execute(select(func.count()).select_from(self.sessions)).scalar_one()
            )
        return SessionStoreStatus(
            store_type="sqlite" if self.url.startswith("sqlite") else "sqlalchemy",
            persistent=True,
            db_url_masked=mask_db_url(self.url),
            ttl_days=self.ttl_days,
            max_messages=self.max_messages,
            session_count=session_count,
        )

    def _ensure_compatible_schema(self) -> None:
        """为已存在的本地 session 表补充新增的可空引用字段。"""

        inspector = inspect(self.engine)
        table_names = set(inspector.get_table_names())
        with self.engine.begin() as conn:
            for table in (self.sessions, self.jobs):
                if table.name not in table_names:
                    continue
                existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing_columns or not column.nullable:
                        continue
                    column_type = column.type.compile(dialect=self.engine.dialect)
                    conn.execute(
                        text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}')
                    )

    def _ensure_session_conn(self, conn: Connection, session_id: str) -> SessionRecord:
        existing = self._get_session_conn(conn, session_id)
        if existing is not None:
            return existing
        now = utc_now()
        record = SessionRecord(
            session_id=session_id,
            title=default_title(session_id),
            created_at=now,
            updated_at=now,
        )
        conn.execute(insert(self.sessions).values(**self._record_values(record)))
        return record

    def _get_session_conn(self, conn: Connection, session_id: str) -> SessionRecord | None:
        row = conn.execute(
            select(self.sessions).where(self.sessions.c.session_id == session_id)
        ).first()
        return None if row is None else self._row_to_record(row._mapping)

    def _touch_session_conn(
        self,
        conn: Connection,
        session_id: str,
        *,
        title: str | None = None,
        datasource_id: str | None | object = _UNSET,
        llm_mode: LLMRuntimeMode | None = None,
        enabled_llm_nodes: list[str] | None = None,
        last_message_preview: str | None = None,
        artifact_refs: Iterable[str] | None = None,
        updated_at: datetime | None = None,
        title_source: SessionTitleSource | None = None,
        summary: str | None = None,
        latest_context: dict[str, object] | None = None,
        context_summary: AgentContextSummary | None = None,
    ) -> SessionRecord:
        current = self._ensure_session_conn(conn, session_id)
        message_count = int(
            conn.execute(
                select(func.count())
                .select_from(self.messages)
                .where(self.messages.c.session_id == session_id)
            ).scalar_one()
        )
        next_record = current.model_copy(
            update={
                "title": title or current.title,
                "summary": summary if summary is not None else current.summary,
                "title_source": title_source or current.title_source,
                "updated_at": updated_at or utc_now(),
                "datasource_id": (
                    current.datasource_id if datasource_id is _UNSET else datasource_id
                ),
                "llm_mode": llm_mode or current.llm_mode,
                "enabled_llm_nodes": (
                    enabled_llm_nodes
                    if enabled_llm_nodes is not None
                    else current.enabled_llm_nodes
                ),
                "message_count": message_count,
                "last_message_preview": last_message_preview or current.last_message_preview,
                "artifact_refs": merge_artifact_refs(
                    current.artifact_refs,
                    artifact_refs or [],
                ),
                "context_summary": (
                    context_summary if context_summary is not None else current.context_summary
                ),
                **(latest_context or {}),
            },
            deep=True,
        )
        conn.execute(
            update(self.sessions)
            .where(self.sessions.c.session_id == session_id)
            .values(**self._record_values(next_record))
        )
        return next_record.model_copy(deep=True)

    def _trim_messages_conn(
        self,
        conn: Connection,
        session_id: str,
        max_messages: int | None,
    ) -> int:
        if max_messages is None or max_messages < 0:
            return 0
        rows = conn.execute(
            select(self.messages.c.message_id)
            .where(self.messages.c.session_id == session_id)
            .order_by(self.messages.c.created_at.asc())
        ).all()
        overflow = max(0, len(rows) - max_messages)
        if overflow <= 0:
            return 0
        message_ids = [row._mapping["message_id"] for row in rows[:overflow]]
        conn.execute(delete(self.messages).where(self.messages.c.message_id.in_(message_ids)))
        return overflow

    def _delete_session_conn(self, conn: Connection, session_id: str) -> None:
        conn.execute(delete(self.messages).where(self.messages.c.session_id == session_id))
        conn.execute(delete(self.jobs).where(self.jobs.c.session_id == session_id))
        conn.execute(delete(self.sessions).where(self.sessions.c.session_id == session_id))

    def _record_values(self, record: SessionRecord) -> dict[str, Any]:
        return {
            "session_id": record.session_id,
            "title": record.title,
            "summary": record.summary,
            "title_source": record.title_source.value,
            "created_at": _dt_to_text(record.created_at),
            "updated_at": _dt_to_text(record.updated_at),
            "datasource_id": record.datasource_id,
            "llm_mode": record.llm_mode.value,
            "enabled_llm_nodes_json": _dump_json(record.enabled_llm_nodes),
            "message_count": record.message_count,
            "last_message_preview": record.last_message_preview,
            "artifact_refs_json": _dump_json(record.artifact_refs),
            "latest_analysis_package_id": record.latest_analysis_package_id,
            "latest_report_outline_id": record.latest_report_outline_id,
            "latest_report_artifact_ref": record.latest_report_artifact_ref,
            "latest_dashboard_artifact_ref": record.latest_dashboard_artifact_ref,
            "latest_excel_artifact_ref": record.latest_excel_artifact_ref,
            "latest_ppt_artifact_ref": record.latest_ppt_artifact_ref,
            "latest_exportable_job_id": record.latest_exportable_job_id,
            "context_summary_json": _dump_json(
                record.context_summary.model_dump(mode="json")
                if record.context_summary is not None
                else None
            ),
        }

    def _message_values(self, message: ChatMessage) -> dict[str, Any]:
        return {
            "message_id": message.message_id,
            "session_id": message.session_id,
            "role": message.role.value,
            "content": message.content,
            "created_at": _dt_to_text(message.created_at),
            "job_id": message.job_id,
            "artifact_refs_json": _dump_json(message.artifact_refs),
            "metadata_json": _dump_json(message.metadata),
        }

    def _job_values(self, job: SessionJobSummary) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": job.status,
            "intent": job.intent,
            "command": job.command,
            "created_at": _dt_to_text(job.created_at),
            "updated_at": _dt_to_text(job.updated_at),
            "final_response_text": job.final_response_text,
            "error_message": job.error_message,
            "needs_human": job.needs_human,
            "artifact_refs_json": _dump_json(job.artifact_refs),
            "analysis_package_id": job.analysis_package_id,
            "report_outline_id": job.report_outline_id,
            "report_artifact_ref": job.report_artifact_ref,
            "dashboard_artifact_ref": job.dashboard_artifact_ref,
            "excel_artifact_ref": job.excel_artifact_ref,
            "ppt_artifact_ref": job.ppt_artifact_ref,
        }

    def _row_to_record(self, row: Any) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            title=row["title"],
            summary=_row_get(row, "summary"),
            title_source=SessionTitleSource(_row_get(row, "title_source") or "rule"),
            created_at=_dt_from_text(row["created_at"]),
            updated_at=_dt_from_text(row["updated_at"]),
            datasource_id=row["datasource_id"],
            llm_mode=LLMRuntimeMode(row["llm_mode"]),
            enabled_llm_nodes=_loads_list(row["enabled_llm_nodes_json"]),
            message_count=row["message_count"],
            last_message_preview=row["last_message_preview"],
            artifact_refs=_loads_list(row["artifact_refs_json"]),
            latest_analysis_package_id=_row_get(row, "latest_analysis_package_id"),
            latest_report_outline_id=_row_get(row, "latest_report_outline_id"),
            latest_report_artifact_ref=_row_get(row, "latest_report_artifact_ref"),
            latest_dashboard_artifact_ref=_row_get(row, "latest_dashboard_artifact_ref"),
            latest_excel_artifact_ref=_row_get(row, "latest_excel_artifact_ref"),
            latest_ppt_artifact_ref=_row_get(row, "latest_ppt_artifact_ref"),
            latest_exportable_job_id=_row_get(row, "latest_exportable_job_id"),
            context_summary=_loads_context_summary(_row_get(row, "context_summary_json")),
        )

    def _row_to_message(self, row: Any) -> ChatMessage:
        return ChatMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            role=ChatRole(row["role"]),
            content=row["content"],
            created_at=_dt_from_text(row["created_at"]),
            job_id=row["job_id"],
            artifact_refs=_loads_list(row["artifact_refs_json"]),
            metadata=_loads_dict(row["metadata_json"]),
        )

    def _row_to_job(self, row: Any) -> SessionJobSummary:
        return SessionJobSummary(
            job_id=row["job_id"],
            session_id=row["session_id"],
            status=row["status"],
            intent=row["intent"],
            command=row["command"],
            created_at=_dt_from_text(row["created_at"]),
            updated_at=_dt_from_text(row["updated_at"]),
            final_response_text=row["final_response_text"],
            error_message=row["error_message"],
            needs_human=bool(row["needs_human"]),
            artifact_refs=_loads_list(row["artifact_refs_json"]),
            analysis_package_id=_row_get(row, "analysis_package_id"),
            report_outline_id=_row_get(row, "report_outline_id"),
            report_artifact_ref=_row_get(row, "report_artifact_ref"),
            dashboard_artifact_ref=_row_get(row, "dashboard_artifact_ref"),
            excel_artifact_ref=_row_get(row, "excel_artifact_ref"),
            ppt_artifact_ref=_row_get(row, "ppt_artifact_ref"),
        )


def _row_get(row: Any, key: str) -> Any:
    try:
        return row[key]
    except KeyError:
        return None


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


def mask_db_url(url: str) -> str:
    """Return a connection URL with passwords hidden."""

    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _loads_context_summary(value: str | None) -> AgentContextSummary | None:
    if not value:
        return None
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        return None
    return AgentContextSummary.model_validate(loaded)


def _dt_to_text(value: datetime) -> str:
    return value.isoformat()


def _dt_from_text(value: str) -> datetime:
    return datetime.fromisoformat(value)
