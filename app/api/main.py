"""FastAPI application skeleton for chat jobs and event inspection."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.schemas import (
    ApproveRequest,
    ChatMessageCreateRequest,
    ChatRequest,
    DataSourceCreateRequest,
    FileDataSourceFromPathRequest,
    JobResponse,
    LLMConfigRequest,
    SessionCleanupRequest,
    SessionCreateRequest,
    SessionDataSourceRequest,
    SessionDataSourceResponse,
    SessionLLMConfigRequest,
    SessionUpdateRequest,
)
from app.config import AppConfig
from app.context_summary import compact_context_summary
from app.harness import LLMNodeStrategyConfig, build_initial_state, infer_command_and_intent
from app.llm_config_store import (
    FileLLMConfigStore,
    LLMConnectionTestResult,
    PublicLLMConfig,
    StoredLLMConfig,
    app_config_updates_from_stored_llm_config,
    model_config_from_stored_llm_config,
)
from app.llm_runtime import (
    LLMRuntimeMode,
    LLMRuntimeStatus,
    SessionLLMConfig,
    build_llm_client_for_session,
)
from app.sessions import (
    ChatMessage,
    ChatRole,
    SessionCleanupResult,
    SessionJobSummary,
    SessionRecord,
    SessionStore,
    SessionTitleSource,
    build_session_store,
    extract_artifact_refs,
    preview_content,
    sanitize_session_title,
)
from app.workers import InMemoryJobRunner, JobRecord, JobStatus, WorkerBackend
from datasource import DataSourceRecord
from datasource.file_datasource import ALLOWED_FILE_SUFFIXES, SENSITIVE_FILE_NAMES
from llm.base import LLMMessage
from llm.errors import LLMAdapterError
from llm.json_utils import extract_json_object
from llm.openai_compatible import OpenAICompatibleClient
from persistence import ArtifactStore
from schemas.agent_state import AgentCommand, AgentIntent
from schemas.analysis_package import AnalysisPackage
from schemas.direct_analysis import QuestionInterpretation
from schemas.event import AgentEvent
from schemas.report import ReportFormat, ReportOutline

SSE_BLOCKED_PAYLOAD_KEYS = frozenset(
    {
        "chart_html",
        "html",
        "file_content",
        "file_bytes",
        "binary",
        "data_url",
    }
)

LOCAL_WEB_UI_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def create_app(
    job_runner: WorkerBackend | None = None,
    session_store: SessionStore | None = None,
    app_config: AppConfig | None = None,
) -> FastAPI:
    """Create a FastAPI app wired to a worker backend."""

    active_config = app_config or getattr(job_runner, "app_config", None) or AppConfig.from_env()
    llm_config_store = FileLLMConfigStore(active_config.llm_config_path)
    stored_llm_config = llm_config_store.load()
    active_config = active_config.with_overrides(
        **app_config_updates_from_stored_llm_config(stored_llm_config)
    )
    app = FastAPI(title="Data Analysis Agent API Skeleton")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_WEB_UI_ORIGINS),
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
    active_runner = job_runner or InMemoryJobRunner(app_config=active_config)
    _apply_runtime_app_config(active_runner, active_config)
    app.state.job_runner = active_runner
    app.state.app_config = active_config
    app.state.llm_config_store = llm_config_store
    app.state.session_store = session_store or build_session_store(active_config)

    @app.get("/health")
    def health(runner: Annotated[WorkerBackend, Depends(get_job_runner)]) -> dict[str, Any]:
        """Return process-local API health without touching external services."""

        return {
            "status": "ok",
            "runner_backend": _runner_backend_name(runner),
        }

    @app.get("/health/runtime")
    def runtime_health(
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> dict[str, Any]:
        """Return runtime configuration health for memory or Celery backend."""

        health_provider = getattr(runner, "runtime_health", None)
        if callable(health_provider):
            runtime = health_provider()
        else:
            runtime = {
                "status": "ok",
                "runner_backend": _runner_backend_name(runner),
                "worker": "local",
            }
        runtime["session_store"] = session_store.status().model_dump(mode="json")
        return runtime

    @app.get("/sessions", response_model=list[SessionRecord])
    def list_sessions(
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> list[SessionRecord]:
        """Return user-visible chat sessions."""

        return session_store.list_sessions()

    @app.post("/sessions", response_model=SessionRecord)
    def create_session(
        session_store: Annotated[SessionStore, Depends(get_session_store)],
        body: SessionCreateRequest | None = None,
    ) -> SessionRecord:
        """Create a user-visible chat session."""

        request_body = body or SessionCreateRequest()
        return session_store.create_session(
            session_id=request_body.session_id,
            title=request_body.title,
        )

    @app.post("/sessions/cleanup", response_model=SessionCleanupResult)
    def cleanup_sessions(
        session_store: Annotated[SessionStore, Depends(get_session_store)],
        body: SessionCleanupRequest | None = None,
    ) -> SessionCleanupResult:
        """Manually delete expired sessions and trim old messages."""

        request_body = body or SessionCleanupRequest()
        return session_store.cleanup_expired_sessions(
            ttl_days=request_body.ttl_days,
            max_messages=request_body.max_messages,
            exclude_session_ids=request_body.exclude_session_ids,
        )

    @app.patch("/sessions/{session_id}", response_model=SessionRecord)
    def update_session(
        session_id: str,
        body: SessionUpdateRequest,
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> SessionRecord:
        """Rename one user-visible chat session."""

        record = session_store.get_session(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
        try:
            return session_store.rename_session(
                session_id,
                title=body.title or record.title,
                title_source=SessionTitleSource.USER,
                summary=body.summary if body.summary is not None else record.summary,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}", response_model=SessionRecord)
    def get_session(
        session_id: str,
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> SessionRecord:
        """Return one user-visible chat session."""

        record = session_store.get_session(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
        return record

    @app.delete("/sessions/{session_id}")
    def delete_session(
        session_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> dict[str, object]:
        """Delete one user-visible chat session and local session preferences."""

        deleted = session_store.delete_session(session_id)
        _delete_runner_session_if_supported(runner, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Unknown session_id: {session_id}")
        return {"deleted": True, "session_id": session_id}

    @app.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
    def list_session_messages(
        session_id: str,
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> list[ChatMessage]:
        """Return visible chat messages for one session."""

        return session_store.list_messages(session_id)

    @app.post("/sessions/{session_id}/messages", response_model=ChatMessage)
    def add_session_message(
        session_id: str,
        body: ChatMessageCreateRequest,
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> ChatMessage:
        """Append one visible chat message without invoking a graph."""

        return session_store.add_message(
            session_id,
            role=body.role,
            content=body.content,
            job_id=body.job_id,
            artifact_refs=body.artifact_refs,
            metadata=body.metadata,
        )

    @app.get("/sessions/{session_id}/jobs", response_model=list[SessionJobSummary])
    def list_session_jobs(
        session_id: str,
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> list[SessionJobSummary]:
        """Return visible job summaries for one session."""

        return session_store.list_jobs(session_id)

    @app.get("/llm/status", response_model=LLMRuntimeStatus)
    def get_llm_status(
        request: Request,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
    ) -> LLMRuntimeStatus:
        """Return safe process-level LLM status without exposing credentials."""

        _refresh_runner_llm_config(request.app, runner, llm_config_store)
        return _get_llm_status(runner)

    @app.get("/llm/config", response_model=PublicLLMConfig)
    def get_llm_config(
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
    ) -> PublicLLMConfig:
        """Return sanitized persisted LLM provider config."""

        return llm_config_store.public_config()

    @app.post("/llm/config", response_model=PublicLLMConfig)
    def save_llm_config(
        body: LLMConfigRequest,
        request: Request,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
    ) -> PublicLLMConfig:
        """Persist global provider config without returning the raw API key."""

        existing = llm_config_store.load()
        api_key = body.api_key.strip() if body.api_key else (existing.api_key if existing else None)
        try:
            saved = llm_config_store.save(
                StoredLLMConfig(
                    provider=body.provider,
                    model=body.model,
                    base_url=body.base_url,
                    api_key=api_key,
                    enabled_nodes=body.enabled_nodes,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _apply_stored_llm_config(request.app, runner, saved)
        return llm_config_store.public_config()

    @app.post("/llm/test", response_model=LLMConnectionTestResult)
    def test_llm_config(
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
        body: LLMConfigRequest | None = None,
    ) -> LLMConnectionTestResult:
        """Run a manual provider connectivity check for saved or provided config."""

        return _test_llm_provider_config(llm_config_store, body)

    @app.get("/sessions/{session_id}/llm", response_model=LLMRuntimeStatus)
    def get_session_llm(
        session_id: str,
        request: Request,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
    ) -> LLMRuntimeStatus:
        """Return the effective LLM rollout config for one session."""

        _refresh_runner_llm_config(request.app, runner, llm_config_store)
        session_record = session_store.ensure_session(session_id)
        _apply_session_preferences_to_runner(
            runner,
            session_record,
            raise_llm_errors=True,
        )
        getter = getattr(runner, "get_session_llm_config", None)
        if callable(getter):
            status = getter(session_id)
        else:
            status = _get_llm_status(runner)
        session_store.update_session_llm_config(
            session_id,
            mode=status.mode,
            enabled_nodes=status.enabled_nodes,
        )
        return status

    @app.post("/sessions/{session_id}/llm", response_model=LLMRuntimeStatus)
    def set_session_llm(
        session_id: str,
        body: SessionLLMConfigRequest,
        request: Request,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
        llm_config_store: Annotated[FileLLMConfigStore, Depends(get_llm_config_store)],
    ) -> LLMRuntimeStatus:
        """Persist a session-scoped LLM mode and enabled node list."""

        _refresh_runner_llm_config(request.app, runner, llm_config_store)
        setter = getattr(runner, "set_session_llm_config", None)
        if not callable(setter):
            raise HTTPException(status_code=501, detail="Session LLM config is not available.")
        try:
            status = setter(
                session_id,
                SessionLLMConfig(mode=body.mode, enabled_nodes=body.enabled_nodes),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session_store.update_session_llm_config(
            session_id,
            mode=status.mode,
            enabled_nodes=status.enabled_nodes,
        )
        return status

    @app.post("/sessions/{session_id}/chat", response_model=JobResponse)
    def create_chat_job(
        session_id: str,
        body: ChatRequest,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> JobResponse:
        """Create a job from chat input and execute it in the local runner."""

        initial_session = session_store.ensure_session(session_id)
        _apply_session_preferences_to_runner(runner, initial_session)
        if body.datasource_id:
            _set_session_datasource_if_supported(runner, session_id, body.datasource_id)
            initial_session = session_store.update_session_datasource(
                session_id,
                body.datasource_id,
            )
        last_analysis_context = _latest_analysis_context_for_session(
            session_store,
            runner,
            session_id,
        )
        route_config = _route_config_for_session(runner, initial_session)
        active_command = body.command
        active_analysis_package = body.analysis_package
        active_report_outline = body.report_outline
        if body.command is AgentCommand.NONE:
            _, inferred_intent = infer_command_and_intent(body.message)
            continuation_command = (
                _export_continuation_command(body.message)
                if inferred_intent is AgentIntent.REPORT_EXPORT
                else None
            )
            if continuation_command is not None:
                latest_export_context = _latest_export_context_for_session(
                    session_store,
                    runner,
                    session_id,
                )
                active_command = continuation_command
                active_analysis_package = latest_export_context.get(
                    "analysis_package",
                    body.analysis_package,
                )
                active_report_outline = latest_export_context.get(
                    "report_outline",
                    body.report_outline,
                )

        state = build_initial_state(
            session_id=session_id,
            user_message=body.message,
            datasource_id=body.datasource_id,
            command=active_command,
            analysis_package=active_analysis_package,
            report_outline=active_report_outline,
            response_language=getattr(
                getattr(runner, "app_config", None),
                "response_language",
                "zh-CN",
            ),
            context_summary=initial_session.context_summary,
            **last_analysis_context,
            **route_config,
        )
        session_store.add_message(
            session_id,
            role=ChatRole.USER,
            content=body.message,
            job_id=state.job_id,
            metadata={
                "command": state.command.value,
                "datasource_id": state.datasource_id,
            },
        )
        _maybe_generate_session_title(
            session_store,
            runner,
            session_id=session_id,
            user_message=body.message,
            intent=state.intent.value,
            initial_session=initial_session,
        )
        record = runner.submit_job(state)
        _write_job_to_session_history(session_store, record)
        return JobResponse.from_record(record)

    @app.get("/datasources", response_model=list[DataSourceRecord])
    def list_datasources(
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> list[DataSourceRecord]:
        """API helper or endpoint."""

        return _list_datasources(runner)

    @app.post("/datasources", response_model=DataSourceRecord)
    def register_datasource(
        body: DataSourceCreateRequest,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> DataSourceRecord:
        """API helper or endpoint."""

        register = getattr(runner, "register_datasource", None)
        if not callable(register):
            raise HTTPException(status_code=501, detail="Datasource registry is not available.")
        try:
            return register(
                datasource_id=body.datasource_id,
                name=body.name,
                kind=body.kind.value,
                url=body.url,
                db_path=body.db_path,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/datasources/from-path", response_model=DataSourceRecord)
    def register_datasource_from_path(
        body: FileDataSourceFromPathRequest,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> DataSourceRecord:
        """API helper or endpoint."""

        register = getattr(runner, "register_file_datasource_from_path", None)
        if not callable(register):
            raise HTTPException(
                status_code=501,
                detail="File datasource registry is not available.",
            )
        datasource_id = body.datasource_id or _datasource_id_from_filename(body.path)
        try:
            return register(
                datasource_id=datasource_id,
                name=body.name,
                file_path=body.path,
                table_name=body.table_name,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/datasources/upload", response_model=DataSourceRecord)
    async def upload_datasource(
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        request: Request,
        file: Annotated[UploadFile, File(description="CSV, xlsx or Parquet datasource file.")],
        datasource_id: Annotated[str | None, Form()] = None,
        name: Annotated[str | None, Form()] = None,
        table_name: Annotated[str | None, Form()] = None,
    ) -> DataSourceRecord:
        """API helper or endpoint."""

        register = getattr(runner, "register_file_datasource_from_upload", None)
        if not callable(register):
            raise HTTPException(
                status_code=501,
                detail="File datasource registry is not available.",
            )
        app_config = _app_config_from_request(request)
        try:
            saved_path = await _save_upload_file(file, app_config)
            return register(
                datasource_id=datasource_id or _datasource_id_from_filename(file.filename or ""),
                name=name,
                saved_path=saved_path,
                original_filename=file.filename or saved_path.name,
                table_name=table_name,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/datasources/{datasource_id}", response_model=DataSourceRecord)
    def get_datasource(
        datasource_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> DataSourceRecord:
        """API helper or endpoint."""

        record = _get_datasource_record(runner, datasource_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown datasource_id: {datasource_id}")
        return record

    @app.post("/datasources/{datasource_id}/profile", response_model=JobResponse)
    def profile_datasource(
        datasource_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> JobResponse:
        """API helper or endpoint."""

        record = _get_datasource_record(runner, datasource_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown datasource_id: {datasource_id}")
        state = build_initial_state(
            session_id=f"datasource-profile-{datasource_id}",
            user_message=f"Profile datasource {datasource_id}",
            datasource_id=datasource_id,
            command="profile",
        )
        return JobResponse.from_record(runner.submit_job(state))

    @app.post(
        "/sessions/{session_id}/datasource",
        response_model=SessionDataSourceResponse,
    )
    def set_session_datasource(
        session_id: str,
        body: SessionDataSourceRequest,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> SessionDataSourceResponse:
        """API helper or endpoint."""

        set_datasource = getattr(runner, "set_session_datasource", None)
        if not callable(set_datasource):
            raise HTTPException(status_code=501, detail="Session datasource is not available.")
        try:
            record = set_datasource(session_id, body.datasource_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        session_store.update_session_datasource(session_id, record.datasource_id)
        return SessionDataSourceResponse(
            session_id=session_id,
            datasource_id=record.datasource_id,
            datasource=record,
        )

    @app.get("/sessions/{session_id}/datasource", response_model=SessionDataSourceResponse)
    def get_session_datasource(
        session_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> SessionDataSourceResponse:
        """API helper or endpoint."""

        getter = getattr(runner, "get_session_datasource", None)
        if not callable(getter):
            raise HTTPException(status_code=501, detail="Session datasource is not available.")
        record = getter(session_id)
        if record is not None:
            session_store.update_session_datasource(session_id, record.datasource_id)
        return SessionDataSourceResponse(
            session_id=session_id,
            datasource_id=record.datasource_id if record is not None else None,
            datasource=record,
        )

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    def get_job(
        job_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> JobResponse:
        """Return one in-memory job status."""

        record = runner.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
        return JobResponse.from_record(record)

    @app.get("/jobs/{job_id}/events", response_model=list[AgentEvent])
    def get_job_events(
        job_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> list[AgentEvent]:
        """Return recorded events for a job without opening an SSE stream."""

        try:
            return runner.list_events(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/events/stream")
    def stream_job_events(
        job_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
    ) -> StreamingResponse:
        """Stream job events as text/event-stream until a terminal event is emitted."""

        if runner.get_job(job_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
        return StreamingResponse(
            _sse_event_stream(runner, job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/jobs/{job_id}/approve", response_model=JobResponse)
    def approve_job(
        job_id: str,
        body: ApproveRequest,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> JobResponse:
        """Resume a waiting export job with an explicit confirm command."""

        try:
            record = runner.approve(job_id, body.command)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _write_job_to_session_history(session_store, record)
        return JobResponse.from_record(record)

    @app.post("/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(
        job_id: str,
        runner: Annotated[WorkerBackend, Depends(get_job_runner)],
        session_store: Annotated[SessionStore, Depends(get_session_store)],
    ) -> JobResponse:
        """Set the job cancel flag and record a stopped event."""

        try:
            record = runner.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _write_job_to_session_history(session_store, record)
        return JobResponse.from_record(record)

    @app.get("/artifacts/{artifact_id}")
    def get_artifact_metadata(
        artifact_id: str,
        artifact_store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    ) -> dict[str, Any]:
        """Return artifact metadata without artifact content."""

        metadata = _load_artifact_metadata(artifact_store, artifact_id)
        return asdict(metadata)

    @app.get("/artifacts/{artifact_id}/content")
    def get_artifact_content(
        artifact_id: str,
        artifact_store: Annotated[ArtifactStore, Depends(get_artifact_store)],
    ) -> Response:
        """Return artifact content using the artifact metadata mime type."""

        metadata = _load_artifact_metadata(artifact_store, artifact_id)
        content = artifact_store.get_artifact_content(artifact_id)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Unknown artifact_id: {artifact_id}")
        media_type = _artifact_media_type(metadata.mime_type, metadata.content_type, content)
        if isinstance(content, bytes):
            return Response(content=content, media_type=media_type)
        if isinstance(content, str):
            return Response(content=content, media_type=media_type)
        return JSONResponse(content=content, media_type=media_type)

    return app


def get_job_runner(request: Request) -> WorkerBackend:
    """Return the configured worker backend from FastAPI app state."""

    return request.app.state.job_runner


def get_session_store(request: Request) -> SessionStore:
    """Return the user-visible session history store."""

    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        app_config = getattr(request.app.state, "app_config", None) or AppConfig.from_env()
        request.app.state.session_store = build_session_store(app_config)
        session_store = request.app.state.session_store
    return session_store


def get_llm_config_store(request: Request) -> FileLLMConfigStore:
    """Return the persisted local LLM config store."""

    store = getattr(request.app.state, "llm_config_store", None)
    if store is None:
        app_config = getattr(request.app.state, "app_config", None) or AppConfig.from_env()
        store = FileLLMConfigStore(app_config.llm_config_path)
        request.app.state.llm_config_store = store
    return store


def get_artifact_store(request: Request) -> ArtifactStore:
    """Return the configured artifact store from app state or the active runner."""

    artifact_store = getattr(request.app.state, "artifact_store", None)
    if artifact_store is not None:
        return artifact_store
    runner = get_job_runner(request)
    runner_artifact_store = getattr(runner, "artifact_store", None)
    if runner_artifact_store is None:
        raise HTTPException(status_code=404, detail="Artifact store is not configured.")
    return runner_artifact_store


def _get_llm_status(runner: WorkerBackend) -> LLMRuntimeStatus:
    """Read safe LLM status from a runner that supports runtime reporting."""

    getter = getattr(runner, "get_llm_status", None)
    if not callable(getter):
        raise HTTPException(status_code=501, detail="LLM status is not available.")
    return getter()


def _apply_runtime_app_config(runner: WorkerBackend, app_config: AppConfig) -> None:
    """Update runner app_config when the backend exposes the local attribute."""

    if hasattr(runner, "app_config"):
        setattr(runner, "app_config", app_config)


def _apply_stored_llm_config(
    app: FastAPI,
    runner: WorkerBackend,
    stored_config: StoredLLMConfig,
) -> None:
    """Apply persisted LLM config to API state and the active local runner."""

    active_config = app.state.app_config.with_overrides(
        **app_config_updates_from_stored_llm_config(stored_config)
    )
    app.state.app_config = active_config
    _apply_runtime_app_config(runner, active_config)


def _refresh_runner_llm_config(
    app: FastAPI,
    runner: WorkerBackend,
    llm_config_store: FileLLMConfigStore,
) -> None:
    """Reload persisted provider settings before validating session LLM mode."""

    stored_config = llm_config_store.load()
    if stored_config is not None:
        _apply_stored_llm_config(app, runner, stored_config)


def _stored_config_from_request(
    llm_config_store: FileLLMConfigStore,
    body: LLMConfigRequest | None,
) -> StoredLLMConfig:
    """Merge a request body with the saved key when the key field is omitted."""

    saved = llm_config_store.load()
    if body is None:
        if saved is None:
            raise ValueError("LLM config is not saved yet.")
        return saved
    api_key = body.api_key.strip() if body.api_key else (saved.api_key if saved else None)
    return StoredLLMConfig(
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
        api_key=api_key,
        enabled_nodes=body.enabled_nodes,
    )


def _test_llm_provider_config(
    llm_config_store: FileLLMConfigStore,
    body: LLMConfigRequest | None,
) -> LLMConnectionTestResult:
    """Check provider connectivity and return only sanitized diagnostics."""

    try:
        stored_config = _stored_config_from_request(llm_config_store, body)
        model_config = model_config_from_stored_llm_config(stored_config)
    except ValueError as exc:
        return LLMConnectionTestResult(
            ok=False,
            message=_sanitize_llm_error(str(exc), body, None),
            error_type="config_invalid",
        )
    try:
        OpenAICompatibleClient(model_config).complete(
            [
                LLMMessage(
                    role="user",
                    content='{"task":"connection_test","expected":"json"}',
                )
            ],
            model=model_config.model,
            temperature=0,
            timeout_seconds=model_config.timeout_seconds,
        )
    except LLMAdapterError as exc:
        return LLMConnectionTestResult(
            ok=False,
            provider=model_config.provider,
            model=model_config.model,
            base_url_host=_safe_url_host(model_config.base_url),
            message=_sanitize_llm_error(exc.detail.message, body, stored_config),
            error_type=exc.detail.code.value,
        )
    except Exception as exc:
        return LLMConnectionTestResult(
            ok=False,
            provider=model_config.provider,
            model=model_config.model,
            base_url_host=_safe_url_host(model_config.base_url),
            message=_sanitize_llm_error(str(exc), body, stored_config),
            error_type=exc.__class__.__name__,
        )
    return LLMConnectionTestResult(
        ok=True,
        provider=model_config.provider,
        model=model_config.model,
        base_url_host=_safe_url_host(model_config.base_url),
        message="LLM provider responded successfully.",
    )


def _maybe_generate_session_title(
    session_store: SessionStore,
    runner: WorkerBackend,
    *,
    session_id: str,
    user_message: str,
    intent: str,
    initial_session: SessionRecord,
) -> None:
    """Optionally replace the rule title with a short LLM title for analysis chats."""

    if initial_session.message_count > 0 or initial_session.title_source is SessionTitleSource.USER:
        return
    if intent in {"clarification", "unknown"}:
        return
    getter = getattr(runner, "get_session_llm_config", None)
    if not callable(getter):
        return
    status = getter(session_id)
    if status.mode not in {LLMRuntimeMode.REAL_LLM, LLMRuntimeMode.FAKE_LLM}:
        return
    app_config = getattr(runner, "app_config", AppConfig.from_env())
    try:
        client = build_llm_client_for_session(
            SessionLLMConfig(mode=status.mode, enabled_nodes=status.enabled_nodes),
            app_config,
        )
        if client is None:
            return
        response = client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "Return a JSON object with short title and summary for a data "
                        "analysis chat. Do not include secrets."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(
                        {"task": "session_title", "user_message": user_message},
                        ensure_ascii=False,
                    ),
                ),
            ],
            temperature=0,
        )
        payload = extract_json_object(response.content)
        title = sanitize_session_title(str(payload.get("title") or user_message))
        summary = preview_content(str(payload.get("summary") or title))
        session_store.rename_session(
            session_id,
            title=title,
            title_source=SessionTitleSource.LLM,
            summary=summary,
        )
    except Exception:
        return


def _sanitize_llm_error(
    message: str,
    body: LLMConfigRequest | None,
    stored_config: StoredLLMConfig | None,
) -> str:
    """Remove known secret values from provider diagnostics."""

    sanitized = str(message or "LLM config test failed.")
    for secret in [
        body.api_key if body is not None else None,
        stored_config.api_key if stored_config is not None else None,
    ]:
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized


def _safe_url_host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    parsed = re.sub(r"^[a-z]+://", "", base_url, flags=re.IGNORECASE).split("/", maxsplit=1)[0]
    return parsed or None


def _write_job_to_session_history(
    session_store: SessionStore,
    record: JobRecord,
) -> None:
    """Write a compact job and assistant summary into user-visible history."""

    _update_context_summary_from_record(session_store, record)
    artifact_refs = _artifact_refs_from_record(record)
    session_store.record_job(
        SessionJobSummary(
            job_id=record.job_id,
            session_id=record.session_id,
            status=record.status.value,
            intent=record.intent.value,
            command=record.command.value,
            created_at=record.created_at,
            updated_at=record.updated_at,
            final_response_text=(
                record.final_state.final_response_text if record.final_state else None
            ),
            error_message=record.error_message,
            needs_human=bool(record.final_state and record.final_state.needs_human),
            artifact_refs=artifact_refs,
            **_session_context_fields_from_record(record),
        )
    )
    session_store.add_message(
        record.session_id,
        role=ChatRole.ASSISTANT,
        content=_assistant_message_for_record(record),
        job_id=record.job_id,
        artifact_refs=artifact_refs,
        metadata={
            "status": record.status.value,
            "intent": record.intent.value,
            "command": record.command.value,
            "needs_human": bool(record.final_state and record.final_state.needs_human),
        },
    )


def _update_context_summary_from_record(
    session_store: SessionStore,
    record: JobRecord,
) -> None:
    """Persist compact workflow context while leaving chat history user-facing."""

    if record.final_state is None:
        return
    current = session_store.get_session(record.session_id)
    previous = current.context_summary if current is not None else None
    context_summary = compact_context_summary(record.final_state, previous=previous)
    record.final_state.context_summary = context_summary
    session_store.update_context_summary(record.session_id, context_summary)


def _artifact_refs_from_record(record: JobRecord) -> list[str]:
    """Extract artifact refs from final state only, never artifact bodies."""

    if record.final_state is None:
        return []
    return extract_artifact_refs(record.final_state)


def _latest_analysis_context_for_session(
    session_store: SessionStore,
    runner: WorkerBackend,
    session_id: str,
) -> dict[str, Any]:
    """Return a compact prior direct-analysis context for follow-up corrections."""

    for summary in session_store.list_jobs(session_id):
        if summary.status != JobStatus.COMPLETED.value:
            continue
        if summary.intent != AgentIntent.DIRECT_ANALYSIS.value:
            continue
        job = runner.get_job(summary.job_id)
        if job is None or job.final_state is None:
            continue
        final_state = job.final_state
        if final_state.question_interpretation is None:
            continue
        return {
            "last_user_question": final_state.user_message,
            "last_question_interpretation": final_state.question_interpretation,
            "last_analysis_plan": final_state.analysis_plan,
            "last_sql_draft": final_state.sql_draft,
            "last_sql_result": final_state.sql_result,
            "last_chart_spec": final_state.chart_spec,
        }
    session = session_store.get_session(session_id)
    context_summary = session.context_summary if session is not None else None
    if context_summary is not None and context_summary.last_question_interpretation is not None:
        try:
            return {
                "last_user_question": context_summary.last_user_question,
                "last_question_interpretation": QuestionInterpretation.model_validate(
                    context_summary.last_question_interpretation
                ),
            }
        except ValueError:
            return {"last_user_question": context_summary.last_user_question}
    return {}


def _latest_export_context_for_session(
    session_store: SessionStore,
    runner: WorkerBackend,
    session_id: str,
) -> dict[str, AnalysisPackage | ReportOutline]:
    """Return the newest reusable export context from prior session jobs."""

    for summary in session_store.list_jobs(session_id):
        if summary.status not in {JobStatus.COMPLETED.value, JobStatus.WAITING_FOR_HUMAN.value}:
            continue
        job = runner.get_job(summary.job_id)
        if job is None or job.final_state is None:
            continue
        final_state = job.final_state
        if final_state.analysis_package is None and final_state.report_outline is None:
            continue
        context: dict[str, AnalysisPackage | ReportOutline] = {}
        if final_state.analysis_package is not None:
            context["analysis_package"] = final_state.analysis_package
        if final_state.report_outline is not None:
            context["report_outline"] = final_state.report_outline
        return context
    return {}


def _export_continuation_command(user_message: str) -> AgentCommand | None:
    """Map follow-up export wording to a guarded confirm command."""

    text = user_message.casefold()
    if _contains_any(text, ("ppt", "powerpoint", "幻灯片", "演示文稿", "演示")):
        return AgentCommand.PPT_CONFIRM
    if _contains_any(text, ("excel", "xlsx", "工作簿")) or (
        "导出" in text and _contains_any(text, ("表格", "表", "xlsx"))
    ):
        return AgentCommand.EXCEL_CONFIRM
    if _contains_any(text, ("dashboard", "看板", "仪表盘")):
        return AgentCommand.DASHBOARD_CONFIRM
    if _contains_any(text, ("继续生成报告", "生成报告", "导出报告", "markdown report", "report")):
        return AgentCommand.REPORT_CONFIRM
    return None


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    """Return whether any token appears in text."""

    return any(token in text for token in tokens)


def _session_context_fields_from_record(record: JobRecord) -> dict[str, str | None]:
    """Extract latest-context ids/refs from a completed job without storing bodies."""

    state = record.final_state
    if state is None:
        return {}
    report_result = state.report_result
    result_ref = report_result.artifact_ref if report_result is not None else None
    return {
        "analysis_package_id": (
            state.analysis_package.package_id if state.analysis_package is not None else None
        ),
        "report_outline_id": (
            state.report_outline.outline_id if state.report_outline is not None else None
        ),
        "report_artifact_ref": (
            result_ref
            if report_result is not None and report_result.report_format is ReportFormat.REPORT
            else None
        ),
        "dashboard_artifact_ref": (
            result_ref
            if report_result is not None and report_result.report_format is ReportFormat.DASHBOARD
            else None
        ),
        "excel_artifact_ref": (
            result_ref
            if report_result is not None and report_result.report_format is ReportFormat.EXCEL
            else None
        ),
        "ppt_artifact_ref": (
            result_ref
            if report_result is not None and report_result.report_format is ReportFormat.PPT
            else None
        ),
    }


def _assistant_message_for_record(record: JobRecord) -> str:
    """Build a compact assistant history message from job status."""

    if record.error_message:
        return f"任务失败：{record.error_message}"
    if record.status.value == "cancelled":
        return "任务已取消。"
    if record.final_state is not None and record.final_state.needs_human:
        human_request = record.final_state.human_request
        prompt = getattr(human_request, "prompt", None) if human_request is not None else None
        return prompt or "等待人工确认。"
    if record.final_state is not None and record.final_state.final_response_text:
        return record.final_state.final_response_text
    return f"任务状态：{record.status.value}。"


def _delete_runner_session_if_supported(runner: WorkerBackend, session_id: str) -> None:
    """Best-effort cleanup for runner-local session preferences."""

    delete_session_state = getattr(runner, "delete_session_state", None)
    if callable(delete_session_state):
        delete_session_state(session_id)


def _list_datasources(runner: WorkerBackend) -> list[DataSourceRecord]:
    """API helper or endpoint."""

    list_records = getattr(runner, "list_datasources", None)
    if not callable(list_records):
        raise HTTPException(status_code=501, detail="Datasource registry is not available.")
    return list_records()


def _get_datasource_record(
    runner: WorkerBackend,
    datasource_id: str,
) -> DataSourceRecord | None:
    """API helper or endpoint."""

    getter = getattr(runner, "get_datasource", None)
    if callable(getter):
        return getter(datasource_id)
    return next(
        (record for record in _list_datasources(runner) if record.datasource_id == datasource_id),
        None,
    )


def _set_session_datasource_if_supported(
    runner: WorkerBackend,
    session_id: str,
    datasource_id: str,
) -> None:
    """API helper or endpoint."""

    setter = getattr(runner, "set_session_datasource", None)
    if not callable(setter):
        return
    try:
        setter(session_id, datasource_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _apply_session_preferences_to_runner(
    runner: WorkerBackend,
    record: SessionRecord,
    *,
    raise_llm_errors: bool = False,
) -> None:
    """Restore persisted session datasource and LLM rollout into a local runner."""

    if record.datasource_id:
        _set_session_datasource_if_supported(runner, record.session_id, record.datasource_id)
    if record.llm_mode is LLMRuntimeMode.RULE and not record.enabled_llm_nodes:
        return
    setter = getattr(runner, "set_session_llm_config", None)
    if not callable(setter):
        return
    try:
        setter(
            record.session_id,
            SessionLLMConfig(
                mode=record.llm_mode,
                enabled_nodes=record.enabled_llm_nodes,
            ),
        )
    except ValueError as exc:
        if raise_llm_errors:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _route_config_for_session(
    runner: WorkerBackend,
    record: SessionRecord,
) -> dict[str, object]:
    """Build optional LLM router injection for the initial app-level route."""

    if record.llm_mode not in {LLMRuntimeMode.REAL_LLM, LLMRuntimeMode.FAKE_LLM}:
        return {}
    if "router" not in record.enabled_llm_nodes:
        return {}
    app_config = getattr(runner, "app_config", None)
    if app_config is None:
        return {}
    session_config = SessionLLMConfig(
        mode=record.llm_mode,
        enabled_nodes=record.enabled_llm_nodes,
    )
    try:
        llm_client = build_llm_client_for_session(session_config, app_config)
    except ValueError:
        return {}
    if llm_client is None:
        return {}
    return {
        "route_strategy": "llm",
        "llm_strategy_config": LLMNodeStrategyConfig(enabled_nodes=["router"]),
        "llm_client": llm_client,
    }


def _app_config_from_request(request: Request) -> AppConfig:
    """API helper or endpoint."""

    return getattr(request.app.state, "app_config", None) or AppConfig.from_env()


async def _save_upload_file(file: UploadFile, app_config: AppConfig) -> Path:
    """API helper or endpoint."""

    original_filename = file.filename or ""
    safe_filename = _safe_upload_filename(original_filename)
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in ALLOWED_FILE_SUFFIXES:
        raise ValueError(
            "Unsupported file datasource type. Allowed extensions: csv, xlsx, parquet."
        )
    max_bytes = _max_upload_bytes(app_config)
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"Uploaded file exceeds limit of {app_config.max_upload_mb} MB.")
    upload_dir = Path(app_config.upload_dir).expanduser().resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid4().hex}_{safe_filename}"
    saved_path.write_bytes(content)
    return saved_path


def _safe_upload_filename(filename: str) -> str:
    """API helper or endpoint."""

    if not filename:
        raise ValueError("Uploaded file must have a filename.")
    if "/" in filename or "\\" in filename:
        raise ValueError("Uploaded filename cannot contain path separators.")
    basename = Path(filename).name.strip()
    if not basename:
        raise ValueError("Uploaded file must have a filename.")
    if basename.lower() in SENSITIVE_FILE_NAMES or basename.lower().startswith(".env"):
        raise ValueError("Sensitive environment files cannot be uploaded as datasources.")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", basename).strip("._")
    if not cleaned or Path(cleaned).suffix.lower() not in ALLOWED_FILE_SUFFIXES:
        raise ValueError(
            "Unsupported file datasource type. Allowed extensions: csv, xlsx, parquet."
        )
    return cleaned


def _datasource_id_from_filename(filename: str) -> str:
    """API helper or endpoint."""

    stem = Path((filename or "file").replace("\\", "/")).stem
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-_").lower()
    return f"file-{normalized or 'datasource'}-{uuid4().hex[:8]}"


def _max_upload_bytes(app_config: AppConfig) -> int:
    """API helper or endpoint."""

    if app_config.max_upload_mb < 1:
        raise ValueError("DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB must be at least 1.")
    return app_config.max_upload_mb * 1024 * 1024


def _runner_backend_name(runner: WorkerBackend) -> str:
    """Return a stable backend label for health responses."""

    class_name = runner.__class__.__name__.lower()
    if "celery" in class_name:
        return "celery"
    if "memory" in class_name:
        return "memory"
    return runner.__class__.__name__


def _sse_event_stream(runner: WorkerBackend, job_id: str) -> Iterator[str]:
    """Encode runner events as SSE frames."""

    for event in runner.stream_events(job_id):
        yield _format_sse_event(event)


def _format_sse_event(event: AgentEvent) -> str:
    """Format one AgentEvent as an SSE frame with typed JSON data."""

    event_payload = _event_stream_payload(event)
    json_payload = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event_type.value}\ndata: {json_payload}\n\n"


def _event_stream_payload(event: AgentEvent) -> dict[str, Any]:
    """Return stream-safe event data without embedding large rendered artifacts."""

    payload = event.model_dump(mode="json")
    payload["payload"] = _sanitize_stream_payload(payload.get("payload", {}))
    return payload


def _load_artifact_metadata(artifact_store: ArtifactStore, artifact_id: str):
    """Load artifact metadata or raise a FastAPI 404."""

    try:
        metadata = artifact_store.get_artifact_metadata(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown artifact_id: {artifact_id}") from exc
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Unknown artifact_id: {artifact_id}")
    return metadata


def _artifact_media_type(
    mime_type: str | None,
    content_type: str | None,
    content: Any,
) -> str:
    """Choose a response media type from artifact metadata and content type."""

    if mime_type:
        return mime_type
    if content_type == "bytes" or isinstance(content, bytes):
        return "application/octet-stream"
    if content_type == "text" or isinstance(content, str):
        return "text/plain"
    return "application/json"


def _sanitize_stream_payload(payload: Any) -> Any:
    """Remove known large artifact bodies from SSE payloads."""

    if isinstance(payload, dict):
        return {
            key: (
                "<omitted>" if key in SSE_BLOCKED_PAYLOAD_KEYS else _sanitize_stream_payload(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitize_stream_payload(item) for item in payload]
    return payload


app = create_app()

__all__ = ["app", "create_app"]
