"""In-memory job runner for app harness and API skeleton tests."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from threading import Condition
from typing import TYPE_CHECKING

from app.config import AppConfig
from app.llm_runtime import (
    LLMRuntimeStats,
    LLMRuntimeStatus,
    SessionLLMConfig,
    build_llm_client_for_session,
    count_llm_events,
    llm_status_from_config,
    node_strategies_for_session,
    normalize_session_llm_config,
    validate_real_llm_session_config,
)
from app.workers.base import WorkerBackend
from app.workers.job_models import TERMINAL_JOB_STATUSES, JobRecord, JobStatus
from datasource.base import DataSource
from datasource.registry import DataSourceRecord, DataSourceRegistry
from graphs.analysis_graph import build_analysis_graph
from graphs.context_manager_graph import build_context_manager_graph
from graphs.open_exploration_graph import build_open_exploration_graph
from graphs.report_graph import build_report_graph
from graphs.schema_qa_graph import build_schema_qa_graph
from guards.cancel_policy import InMemoryCancelPolicy
from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from persistence import (
    ArtifactStore,
    CacheStore,
    CheckpointStore,
    EventStore,
    InMemoryArtifactStore,
    InMemoryCacheStore,
    InMemoryCheckpointStore,
    InMemoryEventStore,
    InMemoryVectorMemoryStore,
    VectorMemoryStore,
)
from schemas._base import utc_now
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.event import AgentEvent, EventType

if TYPE_CHECKING:
    from mcp.manager import MCPManager

TERMINAL_STREAM_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.DONE,
        EventType.ERROR,
        EventType.STOPPED,
    }
)

CLARIFICATION_RESPONSE = (
    "你好，我是数据分析 Agent。普通聊天不会执行 SQL。你可以这样提问："
    "近 12 个月销售趋势怎么样？各品类 GMV Top 5 是什么？"
    "不同地区订单量如何？也可以说：帮我看看这个数据库有什么可以分析的。"
)
NO_DATASOURCE_RESPONSE = (
    "当前会话还没有可用数据源。请先在数据源面板注册或选择一个 datasource，然后再发起数据分析问题。"
)
MULTIPLE_DATASOURCES_RESPONSE = "检测到多个数据源，请先在数据源面板选择当前会话使用的 datasource。"


class InMemoryJobRunner(WorkerBackend):
    """Synchronous process-local runner that wraps existing LangGraph workflows."""

    def __init__(
        self,
        *,
        data_source: DataSource | None = None,
        datasource_registry: DataSourceRegistry | None = None,
        cache_store: CacheStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        event_store: EventStore | None = None,
        artifact_store: ArtifactStore | None = None,
        memory_store: VectorMemoryStore | None = None,
        cancel_policy: InMemoryCancelPolicy | None = None,
        app_config: AppConfig | None = None,
        llm_client: LLMClient | None = None,
        node_strategies: Mapping[str, NodeStrategy] | None = None,
        prompt_loader: PromptLoader | None = None,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        self.app_config = app_config or AppConfig.from_env()
        self.data_source = data_source
        self.datasource_registry = (
            datasource_registry
            if datasource_registry is not None or data_source is not None
            else DataSourceRegistry.from_config(auto_register_demo=True)
        )
        if self.data_source is None and self.datasource_registry is not None:
            only_datasource_id = self.datasource_registry.only_datasource_id()
            if only_datasource_id is not None:
                self.data_source = self.datasource_registry.get_data_source(only_datasource_id)
        self.cache_store = cache_store or InMemoryCacheStore()
        self.checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
        self.event_store = event_store or InMemoryEventStore()
        self.artifact_store = artifact_store or InMemoryArtifactStore()
        self.memory_store = memory_store or InMemoryVectorMemoryStore()
        self.cancel_policy = cancel_policy or InMemoryCancelPolicy()
        self.llm_client = llm_client
        self.node_strategies = dict(node_strategies or {})
        self.prompt_loader = prompt_loader
        self.mcp_manager = mcp_manager
        self._jobs: dict[str, JobRecord] = {}
        self._event_ids_by_job: dict[str, set[str]] = {}
        self._session_datasources: dict[str, str] = {}
        self._session_llm_configs: dict[str, SessionLLMConfig] = {}
        self._last_llm_stats = LLMRuntimeStats()
        self._event_condition = Condition()

    def submit_job(self, state: AgentState) -> JobRecord:
        """Create or replace a local job and execute it synchronously."""

        state = self._hydrate_datasource_id(state)
        job = JobRecord(
            job_id=state.job_id,
            session_id=state.session_id,
            status=JobStatus.PENDING,
            intent=state.intent,
            command=state.command,
            final_state=state,
        )
        self._jobs[state.job_id] = job
        self._event_ids_by_job.setdefault(state.job_id, set())
        return self._run_job(state.job_id, state)

    def submit(self, state: AgentState) -> JobRecord:
        """Compatibility wrapper for older in-memory runner callers."""

        return self.submit_job(state)

    def approve(self, job_id: str, command: AgentCommand | str) -> JobRecord:
        """Resume a waiting export job using an explicit confirm command."""

        job = self._require_job(job_id)
        if job.status is JobStatus.CANCELLED:
            raise ValueError(f"Job '{job_id}' is cancelled and cannot be approved.")
        state = self._load_state_for_job(job)
        state.command = command if isinstance(command, AgentCommand) else AgentCommand(command)
        state.intent = AgentIntent.REPORT_EXPORT
        state.needs_human = False
        return self._run_job(job_id, state)

    def approve_job(self, job_id: str, command: AgentCommand | str) -> JobRecord:
        """Compatibility wrapper for older approve callers."""

        return self.approve(job_id, command)

    def cancel(self, job_id: str) -> JobRecord:
        """Set the cancel flag and mark a local job as cancelled."""

        job = self._require_job(job_id)
        self.cancel_policy.request_cancel(job_id)
        if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED}:
            job = self._update_job(
                job,
                status=JobStatus.CANCELLED,
                error_message=None,
            )
            self._append_job_event(
                job,
                EventType.STOPPED,
                message="Job cancellation requested.",
                payload={"job_id": job_id},
            )
        return job.model_copy(deep=True)

    def cancel_job(self, job_id: str) -> JobRecord:
        """Compatibility wrapper for older cancel callers."""

        return self.cancel(job_id)

    def runtime_health(self) -> dict[str, object]:
        """Return local memory backend health metadata."""

        llm_status = self.get_llm_status()
        return {
            "status": "ok",
            "runner_backend": "memory",
            "worker": "local",
            "data_source_configured": self._datasource_count() > 0,
            "datasource_count": self._datasource_count(),
            "datasource_ids": self._datasource_ids(),
            "llm_mode": llm_status.mode.value,
            "llm_provider": llm_status.provider,
            "llm_model": llm_status.model,
            "llm_base_url_host": llm_status.base_url_host,
            "llm_api_key_configured": llm_status.api_key_configured,
            "llm_enabled_nodes": llm_status.enabled_nodes,
            "cache_store": self.cache_store.__class__.__name__,
            "event_store": self.event_store.__class__.__name__,
            "checkpoint_store": self.checkpoint_store.__class__.__name__,
            "artifact_store": self.artifact_store.__class__.__name__,
            "upload_dir_configured": bool(self.app_config.upload_dir),
            "max_upload_mb": self.app_config.max_upload_mb,
            "local_file_paths_enabled": self.app_config.allow_local_file_paths,
            "job_count": len(self._jobs),
        }

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return a job record by id."""

        job = self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    def get_llm_status(self, session_id: str | None = None) -> LLMRuntimeStatus:
        """Return safe LLM runtime status without exposing credentials."""

        session_config = (
            self._session_llm_configs.get(session_id) if session_id is not None else None
        )
        return llm_status_from_config(
            app_config=self.app_config,
            session_config=session_config,
            stats=self._last_llm_stats,
        )

    def get_session_llm_config(self, session_id: str) -> LLMRuntimeStatus:
        """Return the effective LLM config for one session."""

        return self.get_llm_status(session_id)

    def set_session_llm_config(
        self,
        session_id: str,
        config: SessionLLMConfig,
    ) -> LLMRuntimeStatus:
        """Persist a session-scoped LLM rollout config after validation."""

        normalized_config = normalize_session_llm_config(config)
        validate_real_llm_session_config(normalized_config, self.app_config)
        self._session_llm_configs[session_id] = normalized_config
        return self.get_llm_status(session_id)

    def delete_session_state(self, session_id: str) -> None:
        """Remove process-local session preferences after a session is deleted."""

        self._session_datasources.pop(session_id, None)
        self._session_llm_configs.pop(session_id, None)

    def list_datasources(self) -> list[DataSourceRecord]:
        """返回已注册数据源元数据。"""

        if self.datasource_registry is not None:
            return self.datasource_registry.list_records()
        if self.data_source is None:
            return []
        return [
            DataSourceRecord(
                datasource_id=self.data_source.datasource_id,
                name=self.data_source.datasource_id,
                kind="sqlalchemy",
                status="available",
                created_at=utc_now().isoformat(),
            )
        ]

    def register_datasource(
        self,
        *,
        datasource_id: str,
        name: str | None,
        kind: str,
        url: str | None = None,
        db_path: str | None = None,
    ) -> DataSourceRecord:
        """注册一个新数据源。"""

        self._require_registry()
        return self.datasource_registry.register(
            datasource_id=datasource_id,
            name=name or datasource_id,
            kind=kind,
            url=url,
            db_path=db_path,
        )

    def register_file_datasource_from_path(
        self,
        *,
        datasource_id: str,
        name: str | None,
        file_path: str,
        table_name: str | None = None,
    ) -> DataSourceRecord:
        """注册本地文件路径数据源；默认必须显式开启本地开发开关。"""

        if not self.app_config.allow_local_file_paths:
            raise PermissionError(
                "Local file path datasource registration is disabled. Set "
                "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true for local development."
            )
        self._require_registry()
        return self.datasource_registry.register_file_from_path(
            datasource_id=datasource_id,
            name=name or datasource_id,
            file_path=file_path,
            upload_dir=self.app_config.upload_dir,
            source_type="path",
            table_name=table_name,
            max_bytes=self.app_config.max_upload_mb * 1024 * 1024,
        )

    def register_file_datasource_from_upload(
        self,
        *,
        datasource_id: str,
        name: str | None,
        saved_path: str | Path,
        original_filename: str,
        table_name: str | None = None,
    ) -> DataSourceRecord:
        """注册已保存的上传文件数据源。"""

        self._require_registry()
        return self.datasource_registry.register_file_from_path(
            datasource_id=datasource_id,
            name=name or datasource_id,
            file_path=saved_path,
            upload_dir=self.app_config.upload_dir,
            source_type="upload",
            table_name=table_name,
            original_filename=original_filename,
            max_bytes=self.app_config.max_upload_mb * 1024 * 1024,
        )

    def get_datasource(self, datasource_id: str) -> DataSourceRecord | None:
        """读取一个数据源元数据。"""

        return next(
            (record for record in self.list_datasources() if record.datasource_id == datasource_id),
            None,
        )

    def set_session_datasource(self, session_id: str, datasource_id: str) -> DataSourceRecord:
        """设置会话当前数据源。"""

        record = self.get_datasource(datasource_id)
        if record is None:
            raise KeyError(f"Unknown datasource_id: {datasource_id}")
        self._session_datasources[session_id] = datasource_id
        return record

    def get_session_datasource(self, session_id: str) -> DataSourceRecord | None:
        """读取会话当前数据源；唯一数据源时自动返回该数据源。"""

        datasource_id = self._session_datasources.get(session_id) or self._only_datasource_id()
        if datasource_id is None:
            return None
        return self.get_datasource(datasource_id)

    def list_events(self, job_id: str) -> list[AgentEvent]:
        """Return recorded events for one job."""

        self._require_job(job_id)
        return self.event_store.list_events(job_id=job_id)

    def stream_events(self, job_id: str) -> Iterator[AgentEvent]:
        """Yield recorded and future events for a job until a terminal event appears."""

        self._require_job(job_id)
        next_index = 0
        while True:
            events = self.list_events(job_id)
            while next_index < len(events):
                event = events[next_index]
                next_index += 1
                yield event
                if event.event_type in TERMINAL_STREAM_EVENTS:
                    return

            if self._job_has_terminal_status(job_id):
                return

            with self._event_condition:
                self._event_condition.wait(timeout=0.1)

    def _run_job(self, job_id: str, state: AgentState) -> JobRecord:
        """Execute the selected graph and persist status, events, and state."""

        job = self._require_job(job_id)
        job = self._update_job(
            job,
            status=JobStatus.RUNNING,
            intent=state.intent,
            command=state.command,
            final_state=state,
            error_message=None,
        )
        self._append_job_event(job, EventType.NODE_START, message="Job started.")

        if self.cancel_policy.is_cancelled(job_id):
            return self._cancel_running_job(job, state)

        try:
            if _is_clarification_state(state):
                return self._complete_clarification_job(job, state)
            datasource_blocker_message = self._datasource_blocker_message(state)
            if datasource_blocker_message is not None:
                return self._complete_clarification_job(
                    job,
                    state,
                    message=datasource_blocker_message,
                )
            graph = self._build_graph_for_state(state)
            result_state = AgentState.model_validate(graph.invoke(state))
            self._record_state_events(result_state)
            self.checkpoint_store.save_checkpoint(result_state)
            final_status = (
                JobStatus.WAITING_FOR_HUMAN if result_state.needs_human else JobStatus.COMPLETED
            )
            job = self._update_job(
                job,
                status=final_status,
                intent=result_state.intent,
                command=result_state.command,
                final_state=result_state,
                error_message=None,
            )
            terminal_event_type = (
                EventType.DONE if final_status is JobStatus.COMPLETED else EventType.HUMAN_REQUEST
            )
            if not _state_has_event(result_state, terminal_event_type):
                self._append_job_event(
                    job,
                    terminal_event_type,
                    message=f"Job {final_status.value}.",
                    payload={"job_id": job_id, "status": final_status.value},
                )
        except Exception as exc:
            failed_state = getattr(exc, "state", state)
            if not isinstance(failed_state, AgentState):
                failed_state = state
            user_error_message = _user_visible_error_message(failed_state, exc)
            failed_state.final_response_text = user_error_message
            self._record_state_events(failed_state)
            self.checkpoint_store.save_checkpoint(failed_state)
            job = self._update_job(
                job,
                status=JobStatus.FAILED,
                final_state=failed_state,
                error_message=user_error_message,
            )
            self._append_job_event(
                job,
                EventType.ERROR,
                message=user_error_message,
                payload={
                    "job_id": job_id,
                    "raw_error": str(exc),
                    **_last_error_payload(failed_state),
                },
            )
        self._refresh_last_llm_stats(job_id)
        return job.model_copy(deep=True)

    def _complete_clarification_job(
        self,
        job: JobRecord,
        state: AgentState,
        *,
        message: str | None = None,
    ) -> JobRecord:
        """Return a lightweight Chinese clarification without entering analysis graphs."""

        response_text = message or self._clarification_response_for_state(state)
        llm_status = self.get_llm_status(state.session_id)
        result_state = state.model_copy(
            update={
                "intent": AgentIntent.CLARIFICATION,
                "command": AgentCommand.NONE,
                "needs_human": False,
                "final_response_text": response_text,
            },
            deep=True,
        )
        self._record_state_events(result_state)
        self.checkpoint_store.save_checkpoint(result_state)
        job = self._update_job(
            job,
            status=JobStatus.COMPLETED,
            intent=result_state.intent,
            command=result_state.command,
            final_state=result_state,
            error_message=None,
        )
        self._append_job_event(
            job,
            EventType.TEXT_DELTA,
            message=response_text,
            payload={
                "intent": result_state.intent.value,
                "mode": llm_status.mode.value,
                "provider": llm_status.provider,
                "model": llm_status.model,
                "enabled_nodes": llm_status.enabled_nodes,
            },
        )
        self._append_job_event(
            job,
            EventType.DONE,
            message="任务已完成。",
            payload={"job_id": job.job_id, "status": JobStatus.COMPLETED.value},
        )
        self._refresh_last_llm_stats(job.job_id)
        return job.model_copy(deep=True)

    def _clarification_response_for_state(self, state: AgentState) -> str:
        """Return a Chinese non-SQL response for help and model-status questions."""

        status = self.get_llm_status(state.session_id)
        if _asks_model_status(state.user_message):
            return self._llm_chat_response_for_state(state, status) or _model_status_message(status)
        if status.mode.value in {"real_llm", "fake_llm"}:
            llm_response = self._llm_chat_response_for_state(state, status)
            if llm_response:
                return llm_response
        return f"{CLARIFICATION_RESPONSE} {_mode_summary_message(status)}"

    def _build_graph_for_state(self, state: AgentState):
        """Choose one existing graph from state intent and command."""

        if state.intent is AgentIntent.SCHEMA_QA or state.command is AgentCommand.SCHEMA_QA:
            data_source = self._require_data_source(state.datasource_id)
            return build_schema_qa_graph(
                data_source=data_source,
                cache_store=self.cache_store,
                cancel_policy=self.cancel_policy,
                node_strategy=self._schema_qa_strategy_for_state(state),
                llm_client=self._llm_client_for_state(state),
                prompt_loader=self.prompt_loader,
            )
        if state.intent is AgentIntent.CONTEXT_MANAGER or state.command is AgentCommand.PROFILE:
            data_source = self._require_data_source(state.datasource_id)
            return build_context_manager_graph(
                data_source=data_source,
                cache_store=self.cache_store,
                cancel_policy=self.cancel_policy,
            )
        if state.intent is AgentIntent.OPEN_EXPLORATION or state.command is AgentCommand.EXPLORE:
            data_source = self._require_data_source(state.datasource_id)
            return build_open_exploration_graph(
                data_source=data_source,
                cache_store=self.cache_store,
                cancel_policy=self.cancel_policy,
            )
        if state.intent is AgentIntent.REPORT_EXPORT or state.command in {
            AgentCommand.REPORT,
            AgentCommand.REPORT_CONFIRM,
            AgentCommand.PPT_CONFIRM,
            AgentCommand.EXCEL_CONFIRM,
            AgentCommand.DASHBOARD_CONFIRM,
        }:
            return build_report_graph(
                artifact_store=self.artifact_store,
                cancel_policy=self.cancel_policy,
            )

        data_source = self._require_data_source(state.datasource_id)
        return build_analysis_graph(
            data_source=data_source,
            cache_store=self.cache_store,
            artifact_store=self.artifact_store,
            memory_store=self.memory_store,
            cancel_policy=self.cancel_policy,
            node_strategies=self._node_strategies_for_state(state),
            llm_client=self._llm_client_for_state(state),
            prompt_loader=self.prompt_loader,
        )

    def _cancel_running_job(self, job: JobRecord, state: AgentState) -> JobRecord:
        """Persist cancellation before graph execution starts."""

        self.checkpoint_store.save_checkpoint(state)
        job = self._update_job(job, status=JobStatus.CANCELLED, final_state=state)
        self._append_job_event(
            job,
            EventType.STOPPED,
            message="Job cancelled before graph execution.",
            payload={"job_id": job.job_id},
        )
        self._last_llm_stats = LLMRuntimeStats()
        return job.model_copy(deep=True)

    def _hydrate_datasource_id(self, state: AgentState) -> AgentState:
        """根据请求、会话选择或唯一数据源补齐 datasource_id。"""

        if state.datasource_id is not None:
            if self.get_datasource(state.datasource_id) is not None:
                self._session_datasources[state.session_id] = state.datasource_id
            return state
        session_datasource_id = self._session_datasources.get(state.session_id)
        if session_datasource_id is not None:
            return state.model_copy(update={"datasource_id": session_datasource_id})
        only_datasource_id = self._only_datasource_id()
        if only_datasource_id is not None:
            return state.model_copy(update={"datasource_id": only_datasource_id})
        return state

    def _load_state_for_job(self, job: JobRecord) -> AgentState:
        """Load the last checkpoint or final state for a job."""

        checkpoint = self.checkpoint_store.load_checkpoint(job.session_id, job.job_id)
        if checkpoint is not None:
            return checkpoint
        if job.final_state is not None:
            return job.final_state.model_copy(deep=True)
        raise ValueError(f"Job '{job.job_id}' has no state to resume.")

    def _record_state_events(self, state: AgentState) -> None:
        """Copy unseen AgentState events into the shared event store."""

        seen_event_ids = self._event_ids_by_job.setdefault(state.job_id, set())
        for event in state.events:
            if event.event_id in seen_event_ids:
                continue
            self._append_event_to_store(event)
            seen_event_ids.add(event.event_id)
        if state.database_profile is not None and self.datasource_registry is not None:
            self.datasource_registry.mark_profiled(
                state.database_profile.datasource_id,
                state.database_profile.schema_hash,
            )

    def _refresh_last_llm_stats(self, job_id: str) -> None:
        """Update process-local LLM counters from recorded job events."""

        self._last_llm_stats = count_llm_events(self.event_store.list_events(job_id=job_id))

    def _append_job_event(
        self,
        job: JobRecord,
        event_type: EventType,
        *,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        """Append a job-scoped event outside graph node execution."""

        event = AgentEvent(
            event_type=event_type,
            session_id=job.session_id,
            job_id=job.job_id,
            node_name="job_runner",
            message=message,
            payload=payload or {},
        )
        self._append_event_to_store(event)
        self._event_ids_by_job.setdefault(job.job_id, set()).add(event.event_id)

    def _append_event_to_store(self, event: AgentEvent) -> None:
        """Append an event and wake in-memory stream subscribers."""

        with self._event_condition:
            self.event_store.append_event(event)
            self._event_condition.notify_all()

    def _update_job(self, job: JobRecord, **updates: object) -> JobRecord:
        """Update a job record and refresh its timestamp."""

        updated_job = job.model_copy(
            update={
                **updates,
                "updated_at": utc_now(),
            },
            deep=True,
        )
        self._jobs[updated_job.job_id] = updated_job
        return updated_job

    def _require_job(self, job_id: str) -> JobRecord:
        """Return a job or raise a stable KeyError."""

        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"Unknown job_id: {job_id}") from exc

    def _job_has_terminal_status(self, job_id: str) -> bool:
        """Return whether the job cannot produce more events."""

        job = self._require_job(job_id)
        return job.status in TERMINAL_JOB_STATUSES

    def _node_strategies_for_state(self, state: AgentState) -> dict[str, NodeStrategy]:
        """Return node strategies for the session, preserving legacy runner injection."""

        session_config = self._session_llm_configs.get(state.session_id)
        if session_config is None:
            return dict(self.node_strategies)
        return node_strategies_for_session(session_config)

    def _llm_client_for_state(self, state: AgentState) -> LLMClient | None:
        """Return the LLM client selected for the session without changing defaults."""

        session_config = self._session_llm_configs.get(state.session_id)
        if session_config is None:
            return self.llm_client
        return build_llm_client_for_session(session_config, self.app_config)

    def _schema_qa_strategy_for_state(self, state: AgentState) -> NodeStrategy:
        """Use LLM only as a no-tools schema answer writer when session mode enables it."""

        session_config = self._session_llm_configs.get(state.session_id)
        if session_config is None:
            return "llm" if self.llm_client is not None else "rule"
        return "llm" if session_config.mode.value in {"real_llm", "fake_llm"} else "rule"

    def _llm_chat_response_for_state(
        self,
        state: AgentState,
        status: LLMRuntimeStatus,
    ) -> str | None:
        """Call a no-tools chat responder when real/fake LLM mode is enabled."""

        llm_client = self._llm_client_for_state(state)
        if llm_client is None or status.mode.value not in {"real_llm", "fake_llm"}:
            return None
        try:
            payload = call_llm_for_json(
                llm_client=llm_client,
                prompt_name="chat_responder",
                prompt_loader=self.prompt_loader,
                state=state,
                node_name="chat_responder",
                user_payload={
                    "task": "chat_responder",
                    "user_message": state.user_message,
                    "llm_status": status.model_dump(mode="json"),
                    "language": state.response_language,
                },
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="chat_responder",
                prompt_name="chat_responder",
                llm_client=llm_client,
                exc=exc,
            )
            return None
        answer = str(payload.get("answer") or "").strip()
        return answer or None

    def _require_data_source(self, datasource_id: str | None) -> DataSource:
        """Return the configured datasource or fail with a clear app wiring error."""

        if self.datasource_registry is not None:
            if datasource_id is None:
                raise ValueError("Select a datasource before starting analysis.")
            return self.datasource_registry.get_data_source(datasource_id)
        if self.data_source is None:
            raise ValueError("InMemoryJobRunner requires a datasource for analysis workflows.")
        return self.data_source

    def _require_registry(self) -> None:
        """确保当前 runner 支持 datasource registry。"""

        if self.datasource_registry is None:
            self.datasource_registry = DataSourceRegistry()

    def _datasource_count(self) -> int:
        """返回可用数据源数量。"""

        return len(self._datasource_ids())

    def _datasource_ids(self) -> list[str]:
        """返回当前 runner 可识别的数据源 ID。"""

        if self.datasource_registry is not None:
            return [record.datasource_id for record in self.datasource_registry.list_records()]
        if self.data_source is not None:
            return [self.data_source.datasource_id]
        return []

    def _only_datasource_id(self) -> str | None:
        """只有一个数据源时返回其 ID。"""

        datasource_ids = self._datasource_ids()
        return datasource_ids[0] if len(datasource_ids) == 1 else None

    def _datasource_blocker_message(self, state: AgentState) -> str | None:
        """分析类请求缺少明确数据源时返回提示文案。"""

        if not _state_requires_datasource(state):
            return None
        if state.datasource_id is not None:
            return None
        datasource_count = self._datasource_count()
        if datasource_count == 0:
            return NO_DATASOURCE_RESPONSE
        if datasource_count > 1:
            return MULTIPLE_DATASOURCES_RESPONSE
        return None


def _state_has_event(state: AgentState, event_type: EventType) -> bool:
    """Return whether a graph state already emitted a job-scoped event type."""

    return any(event.event_type is event_type for event in state.events)


def _user_visible_error_message(state: AgentState, exc: Exception) -> str:
    """Return a concise Chinese error for chat/history while keeping details in events."""

    if state.errors:
        message = state.errors[-1].message.strip()
        if message:
            return _localize_error_message(message)
    return _localize_error_message(str(exc))


def _localize_error_message(message: str) -> str:
    """Map common internal errors to user-facing Chinese summaries."""

    normalized = message.strip()
    if not normalized:
        return "任务执行失败：请在开发者详情查看错误信息。"
    if normalized.startswith("Node '"):
        return "任务执行失败：内部节点执行失败，请在开发者详情查看错误信息。"
    if "SQL must be valid before execution" in normalized:
        return "SQL 校验失败，已停止执行，未访问数据库。"
    return normalized


def _last_error_payload(state: AgentState) -> dict[str, object]:
    """Expose bounded developer diagnostics for the last structured state error."""

    if not state.errors:
        return {}
    error = state.errors[-1]
    return {
        "error_id": error.error_id,
        "code": error.code,
        "node_name": error.node_name,
        "details": error.details,
    }


def _is_clarification_state(state: AgentState) -> bool:
    """判断请求是否应在不访问 SQL 或数据源的情况下完成。"""

    return state.intent in {AgentIntent.CLARIFICATION, AgentIntent.UNKNOWN}


def _state_requires_datasource(state: AgentState) -> bool:
    """判断当前工作流是否需要数据源。"""

    return state.intent in {
        AgentIntent.CONTEXT_MANAGER,
        AgentIntent.DIRECT_ANALYSIS,
        AgentIntent.OPEN_EXPLORATION,
        AgentIntent.SCHEMA_QA,
    } or state.command in {
        AgentCommand.PROFILE,
        AgentCommand.ANALYZE,
        AgentCommand.EXPLORE,
        AgentCommand.SCHEMA_QA,
    }


def _asks_model_status(user_message: str) -> bool:
    """Detect model-status chat without sending the message to analysis graphs."""

    text = user_message.casefold()
    return any(
        token in text
        for token in (
            "什么模型",
            "哪个模型",
            "当前模型",
            "用的什么模型",
            "你是deepseek",
            "你是 deepseek",
            "deepseek吗",
            "model",
            "provider",
        )
    )


def _model_status_message(status: LLMRuntimeStatus) -> str:
    """Return a Chinese runtime status answer without exposing secrets."""

    if status.mode.value == "real_llm":
        provider_model = _provider_model(status)
        nodes = _enabled_nodes_text(status.enabled_nodes)
        return f"当前已配置真实模型：{provider_model}。启用的模型节点包括：{nodes}。"
    if status.mode.value == "fake_llm":
        nodes = _enabled_nodes_text(status.enabled_nodes)
        return f"当前使用 fake LLM 测试模式，启用的模型节点包括：{nodes}。"
    return "当前使用规则模式，未启用真实模型节点。普通聊天不会执行 SQL。"


def _mode_summary_message(status: LLMRuntimeStatus) -> str:
    """Return a short Chinese mode summary for help replies."""

    if status.mode.value == "real_llm":
        return f"当前模型模式为 real_llm，已配置 {_provider_model(status)}。"
    if status.mode.value == "fake_llm":
        return "当前模型模式为 fake_llm，仅用于本地测试。"
    return "当前使用规则模式，未启用真实模型节点。"


def _provider_model(status: LLMRuntimeStatus) -> str:
    provider = status.provider or "unknown-provider"
    model = status.model or "unknown-model"
    return f"{provider}/{model}"


def _enabled_nodes_text(enabled_nodes: list[str]) -> str:
    return "、".join(enabled_nodes) if enabled_nodes else "无"


__all__ = ["InMemoryJobRunner", "JobRecord", "JobStatus", "TERMINAL_STREAM_EVENTS"]
