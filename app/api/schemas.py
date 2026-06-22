"""Request and response schemas for the FastAPI skeleton."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.llm_config_store import LLMProviderName
from app.llm_runtime import LLMRuntimeMode
from app.sessions import ChatRole
from app.workers import JobRecord, JobStatus
from datasource import DataSourceKind, DataSourceRecord
from schemas._base import StrictBaseModel
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.report import ReportOutline


class ChatRequest(StrictBaseModel):
    """Input accepted by the local chat job endpoint."""

    message: str
    datasource_id: str | None = None
    command: AgentCommand = AgentCommand.NONE
    analysis_package: AnalysisPackage | None = None
    report_outline: ReportOutline | None = None


class ApproveRequest(StrictBaseModel):
    """Explicit confirmation command used by the export fast-path endpoint."""

    command: AgentCommand = Field(
        description="One of report_confirm, ppt_confirm, excel_confirm, dashboard_confirm."
    )


class DataSourceCreateRequest(StrictBaseModel):
    """娉ㄥ唽 sqlite 鎴?SQLAlchemy 鏁版嵁婧愮殑 API 杈撳叆銆?"""

    datasource_id: str
    name: str | None = None
    kind: DataSourceKind = DataSourceKind.SQLITE
    url: str | None = None
    db_path: str | None = None


class FileDataSourceFromPathRequest(StrictBaseModel):
    """閫氳繃鏈湴鏂囦欢璺緞娉ㄥ唽鏂囦欢鏁版嵁婧愮殑 API 杈撳叆銆?"""

    path: str
    datasource_id: str | None = None
    name: str | None = None
    table_name: str | None = None


class SessionDataSourceRequest(StrictBaseModel):
    """璁剧疆褰撳墠浼氳瘽鏁版嵁婧愮殑 API 杈撳叆銆?"""

    datasource_id: str


class SessionDataSourceResponse(StrictBaseModel):
    """褰撳墠浼氳瘽鏁版嵁婧愰€夋嫨缁撴灉銆?"""

    session_id: str
    datasource_id: str | None = None
    datasource: DataSourceRecord | None = None


class SessionLLMConfigRequest(StrictBaseModel):
    """Session-scoped LLM mode and node rollout request."""

    mode: LLMRuntimeMode = LLMRuntimeMode.RULE
    enabled_nodes: list[str] = Field(default_factory=list)


class LLMConfigRequest(StrictBaseModel):
    """Persisted provider config accepted by the product LLM settings UI."""

    provider: LLMProviderName = LLMProviderName.OPENAI_COMPATIBLE
    model: str
    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    enabled_nodes: list[str] = Field(default_factory=list)


class SessionUpdateRequest(StrictBaseModel):
    """Patch user-visible session metadata without touching workflow state."""

    title: str | None = None
    summary: str | None = None


class SessionCreateRequest(StrictBaseModel):
    """Create a user-visible chat session."""

    session_id: str | None = None
    title: str | None = None


class SessionCleanupRequest(StrictBaseModel):
    """Manual session history cleanup options."""

    ttl_days: int | None = None
    max_messages: int | None = None
    exclude_session_ids: list[str] = Field(default_factory=list)


class ChatMessageCreateRequest(StrictBaseModel):
    """Append a visible chat message without touching workflow state."""

    role: ChatRole = ChatRole.USER
    content: str
    job_id: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class JobResponse(StrictBaseModel):
    """API-safe job view with status and the latest state snapshot."""

    job_id: str
    session_id: str
    status: JobStatus
    intent: AgentIntent
    command: AgentCommand
    needs_human: bool = False
    final_response_text: str | None = None
    error_message: str | None = None
    final_state: AgentState | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResponse:
        """Build a response model from an internal job record."""

        return cls(
            job_id=record.job_id,
            session_id=record.session_id,
            status=record.status,
            intent=record.intent,
            command=record.command,
            needs_human=bool(record.final_state and record.final_state.needs_human),
            final_response_text=(
                record.final_state.final_response_text if record.final_state else None
            ),
            error_message=record.error_message,
            final_state=record.final_state,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
