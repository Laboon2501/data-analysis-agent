"""Celery worker backend backed by shared persistence stores."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import (
    ARTIFACT_DIR_ENV,
    CELERY_BROKER_URL_ENV,
    CELERY_QUEUE_ENV,
    CELERY_RESULT_BACKEND_ENV,
    CELERY_TASK_NAME_ENV,
    DEFAULT_CELERY_TASK_NAME,
    REDIS_URL_ENV,
    AppConfig,
)
from app.workers.base import WorkerBackend
from app.workers.celery_state import (
    clear_cancel_flag,
    compact_error_payload,
    load_job_record,
    save_cancel_flag,
    save_job_record,
)
from app.workers.datasource_state import (
    delete_session_datasource,
    load_datasource_registry,
    load_session_datasource,
    save_datasource_registry,
    save_session_datasource,
)
from app.workers.job_models import TERMINAL_JOB_STATUSES, JobRecord, JobStatus
from datasource import DataSourceRecord
from persistence import (
    ArtifactStore,
    CacheStore,
    CheckpointStore,
    EventStore,
    FileArtifactStore,
    InMemoryCacheStore,
    InMemoryCheckpointStore,
    InMemoryEventStore,
    PostgresCheckpointStore,
    RedisCacheStore,
    RedisEventStore,
)
from schemas._base import StrictBaseModel, utc_now
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.event import AgentEvent, EventType

TaskSubmitter = Callable[["CeleryRunnerConfig", dict[str, Any]], str | None]


@dataclass(frozen=True)
class CeleryStoreBundle:
    """Persistence stores shared by the API process and Celery tasks."""

    cache_store: CacheStore
    checkpoint_store: CheckpointStore
    event_store: EventStore
    artifact_store: ArtifactStore


class CeleryRunnerConfig(StrictBaseModel):
    """Environment-backed configuration for the Celery backend."""

    broker_url: str | None = None
    result_backend: str | None = None
    queue_name: str = "data-analysis-agent"
    task_name: str = DEFAULT_CELERY_TASK_NAME

    @classmethod
    def from_env(cls) -> CeleryRunnerConfig:
        """Build Celery configuration from environment variables."""

        return cls.from_app_config(AppConfig.from_env())

    @classmethod
    def from_app_config(cls, config: AppConfig) -> CeleryRunnerConfig:
        """Build Celery configuration from central AppConfig."""

        return cls(
            broker_url=config.celery_broker_url,
            result_backend=config.celery_result_backend,
            queue_name=config.celery_queue,
            task_name=config.celery_task_name,
        )

    def require_broker(self) -> None:
        """Raise a clear error when Celery cannot submit tasks."""

        if not self.broker_url:
            raise RuntimeError(
                f"Celery backend requires {CELERY_BROKER_URL_ENV} or an injected task_submitter."
            )


class CeleryWorkerBackend(WorkerBackend):
    """Celery-backed implementation of the shared worker contract."""

    def __init__(
        self,
        *,
        app_config: AppConfig | None = None,
        config: CeleryRunnerConfig | None = None,
        cache_store: CacheStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        event_store: EventStore | None = None,
        artifact_store: ArtifactStore | None = None,
        task_submitter: TaskSubmitter | None = None,
    ) -> None:
        self.app_config = app_config or AppConfig.from_env()
        self.config = config or CeleryRunnerConfig.from_app_config(self.app_config)
        default_stores = None
        if not all(
            store is not None
            for store in (cache_store, checkpoint_store, event_store, artifact_store)
        ):
            default_stores = celery_store_bundle_from_config(self.config, self.app_config)
        self.cache_store = cache_store or default_stores.cache_store
        self.checkpoint_store = checkpoint_store or default_stores.checkpoint_store
        self.event_store = event_store or default_stores.event_store
        self.artifact_store = artifact_store or default_stores.artifact_store
        self.datasource_registry = load_datasource_registry(self.cache_store, self.app_config)
        self.task_submitter = task_submitter
        self._jobs: dict[str, JobRecord] = {}
        self._external_task_ids: dict[str, str] = {}

    def submit_job(self, state: AgentState) -> JobRecord:
        """Persist a pending job and submit it to Celery."""

        state = self._hydrate_datasource_id(state)
        clear_cancel_flag(self.cache_store, state.job_id)
        job = self._save_job(
            JobRecord(
                job_id=state.job_id,
                session_id=state.session_id,
                status=JobStatus.PENDING,
                intent=state.intent,
                command=state.command,
                final_state=state,
            )
        )
        return self._submit_state(job, state, message="Job submitted to Celery backend.")

    def submit(self, state: AgentState) -> JobRecord:
        """Compatibility wrapper mirroring InMemoryJobRunner."""

        return self.submit_job(state)

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return a job record from shared stores."""

        job = load_job_record(self.cache_store, job_id) or self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    def list_events(self, job_id: str) -> list[AgentEvent]:
        """Return recorded events for one Celery job."""

        self._require_job(job_id)
        return self.event_store.list_events(job_id=job_id)

    def stream_events(self, job_id: str) -> Iterator[AgentEvent]:
        """Yield stored events through the configured EventStore."""

        self._require_job(job_id)
        stream_events = getattr(self.event_store, "stream_events", None)
        if callable(stream_events):
            yield from stream_events(job_id=job_id)
            return
        for event in self.list_events(job_id):
            yield event
            if event.event_type in {EventType.DONE, EventType.ERROR, EventType.STOPPED}:
                return

    def approve(self, job_id: str, command: AgentCommand | str) -> JobRecord:
        """Resume a waiting export job with an explicit confirm command."""

        job = self._require_job(job_id)
        if job.status is JobStatus.CANCELLED:
            raise ValueError(f"Job '{job_id}' is cancelled and cannot be approved.")
        state = self._load_state_for_job(job)
        state.command = command if isinstance(command, AgentCommand) else AgentCommand(command)
        state.intent = AgentIntent.REPORT_EXPORT
        state.needs_human = False
        clear_cancel_flag(self.cache_store, job_id)
        pending_job = self._save_job(
            _updated_job(
                job,
                status=JobStatus.PENDING,
                command=state.command,
                intent=state.intent,
                final_state=state,
                error_message=None,
            )
        )
        return self._submit_state(
            pending_job,
            state,
            message="Approval submitted to Celery backend.",
            payload={"command": state.command.value},
        )

    def approve_job(self, job_id: str, command: AgentCommand | str) -> JobRecord:
        """Compatibility wrapper mirroring InMemoryJobRunner."""

        return self.approve(job_id, command)

    def cancel(self, job_id: str) -> JobRecord:
        """Set a shared cancel flag, update job status, and emit stopped."""

        job = self._require_job(job_id)
        save_cancel_flag(self.cache_store, job_id)
        cancelled_job = job
        if job.status not in TERMINAL_JOB_STATUSES:
            cancelled_job = self._save_job(_updated_job(job, status=JobStatus.CANCELLED))
            self._append_event(
                cancelled_job,
                EventType.STOPPED,
                message="Celery job cancellation requested.",
                payload={
                    "job_id": job_id,
                    "external_task_id": self._external_task_ids.get(job_id),
                },
            )
        return cancelled_job.model_copy(deep=True)

    def cancel_job(self, job_id: str) -> JobRecord:
        """Compatibility wrapper mirroring InMemoryJobRunner."""

        return self.cancel(job_id)

    def runtime_health(self) -> dict[str, object]:
        """Return Celery runtime configuration health without contacting workers."""

        redis_configured = bool(self.app_config.effective_redis_url)
        broker_configured = bool(self.config.broker_url)
        return {
            "status": "ok" if broker_configured and redis_configured else "degraded",
            "runner_backend": "celery",
            "worker": "external",
            "broker_configured": broker_configured,
            "result_backend_configured": bool(self.config.result_backend),
            "redis_events_configured": redis_configured,
            "checkpoint_configured": bool(self.app_config.effective_checkpoint_url),
            "artifact_store": self.artifact_store.__class__.__name__,
            "artifact_dir": self.app_config.artifact_dir,
            "upload_dir_configured": bool(self.app_config.upload_dir),
            "max_upload_mb": self.app_config.max_upload_mb,
            "local_file_paths_enabled": self.app_config.allow_local_file_paths,
            "queue_name": self.config.queue_name,
            "task_name": self.config.task_name,
            "worker_online_checked": False,
        }

    def list_datasources(self) -> list[DataSourceRecord]:
        """返回共享 datasource registry 中的安全 metadata。"""

        self._refresh_datasource_registry()
        return self.datasource_registry.list_records()

    def register_datasource(
        self,
        *,
        datasource_id: str,
        name: str | None,
        kind: str,
        url: str | None = None,
        db_path: str | None = None,
    ) -> DataSourceRecord:
        """注册 SQL datasource 并写入共享 registry。"""

        self._refresh_datasource_registry()
        record = self.datasource_registry.register(
            datasource_id=datasource_id,
            name=name or datasource_id,
            kind=kind,
            url=url,
            db_path=db_path,
        )
        self._save_datasource_registry()
        return record

    def register_file_datasource_from_path(
        self,
        *,
        datasource_id: str,
        name: str | None,
        file_path: str,
        table_name: str | None = None,
    ) -> DataSourceRecord:
        """注册本地文件路径 datasource；默认需要显式开启本地开发开关。"""

        if not self.app_config.allow_local_file_paths:
            raise PermissionError(
                "Local file path datasource registration is disabled. Set "
                "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true for local development."
            )
        self._refresh_datasource_registry()
        record = self.datasource_registry.register_file_from_path(
            datasource_id=datasource_id,
            name=name or datasource_id,
            file_path=file_path,
            upload_dir=self.app_config.upload_dir,
            source_type="path",
            table_name=table_name,
            max_bytes=self.app_config.max_upload_mb * 1024 * 1024,
        )
        self._save_datasource_registry()
        return record

    def register_file_datasource_from_upload(
        self,
        *,
        datasource_id: str,
        name: str | None,
        saved_path: str | Path,
        original_filename: str,
        table_name: str | None = None,
    ) -> DataSourceRecord:
        """注册上传文件 datasource，并把内部 SQLite URL 写入共享 registry。"""

        self._refresh_datasource_registry()
        record = self.datasource_registry.register_file_from_path(
            datasource_id=datasource_id,
            name=name or datasource_id,
            file_path=saved_path,
            upload_dir=self.app_config.upload_dir,
            source_type="upload",
            table_name=table_name,
            original_filename=original_filename,
            max_bytes=self.app_config.max_upload_mb * 1024 * 1024,
        )
        self._save_datasource_registry()
        return record

    def get_datasource(self, datasource_id: str) -> DataSourceRecord | None:
        """读取一个 datasource metadata。"""

        self._refresh_datasource_registry()
        return self.datasource_registry.get_record(datasource_id)

    def set_session_datasource(self, session_id: str, datasource_id: str) -> DataSourceRecord:
        """保存 session 当前 datasource 到共享 cache。"""

        record = self.get_datasource(datasource_id)
        if record is None:
            raise KeyError(f"Unknown datasource_id: {datasource_id}")
        save_session_datasource(self.cache_store, session_id, datasource_id)
        return record

    def get_session_datasource(self, session_id: str) -> DataSourceRecord | None:
        """读取 session datasource；唯一 datasource 时自动返回该 datasource。"""

        self._refresh_datasource_registry()
        datasource_id = (
            load_session_datasource(self.cache_store, session_id)
            or self.datasource_registry.only_datasource_id()
        )
        if datasource_id is None:
            return None
        return self.datasource_registry.get_record(datasource_id)

    def delete_session_state(self, session_id: str) -> None:
        """删除共享 session datasource 选择。"""

        delete_session_datasource(self.cache_store, session_id)

    def _submit_state(
        self,
        job: JobRecord,
        state: AgentState,
        *,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> JobRecord:
        """Submit one serialized state through fake hook or real Celery."""

        try:
            task_id = self._submit_task(state)
        except Exception as exc:
            error_payload = compact_error_payload(exc)
            failed_job = self._save_job(
                _updated_job(job, status=JobStatus.FAILED, error_message=error_payload["message"])
            )
            self._append_event(
                failed_job,
                EventType.ERROR,
                message=error_payload["message"],
                payload={"job_id": job.job_id, **error_payload},
            )
            message_text = error_payload["message"]
            raise RuntimeError(f"Celery task submission failed: {message_text}") from exc

        event_payload: dict[str, object] = {
            "job_id": job.job_id,
            "queue_name": self.config.queue_name,
            "task_name": self.config.task_name,
            "submitted": task_id is not None,
            **(payload or {}),
        }
        if task_id is not None:
            self._external_task_ids[job.job_id] = task_id
            event_payload["external_task_id"] = task_id
        self._append_event(job, EventType.NODE_START, message=message, payload=event_payload)
        return job.model_copy(deep=True)

    def _hydrate_datasource_id(self, state: AgentState) -> AgentState:
        """根据请求、session 选择或唯一 datasource 补齐 datasource_id。"""

        if state.datasource_id is not None:
            if self.get_datasource(state.datasource_id) is not None:
                save_session_datasource(self.cache_store, state.session_id, state.datasource_id)
            return state
        session_datasource_id = load_session_datasource(self.cache_store, state.session_id)
        if session_datasource_id is not None:
            return state.model_copy(update={"datasource_id": session_datasource_id})
        only_datasource_id = self.datasource_registry.only_datasource_id()
        if only_datasource_id is not None:
            return state.model_copy(update={"datasource_id": only_datasource_id})
        return state

    def _refresh_datasource_registry(self) -> None:
        """从共享 cache 刷新 datasource registry。"""

        self.datasource_registry = load_datasource_registry(self.cache_store, self.app_config)

    def _save_datasource_registry(self) -> None:
        """保存 datasource registry 到共享 cache。"""

        save_datasource_registry(self.cache_store, self.datasource_registry)

    def _submit_task(self, state: AgentState) -> str | None:
        """Submit through an injected fake or a real Celery app."""

        payload = {
            "job_id": state.job_id,
            "session_id": state.session_id,
            "state": state.model_dump(mode="json"),
        }
        if self.task_submitter is not None:
            return self.task_submitter(self.config, payload)

        self.config.require_broker()
        self._require_shared_stores()
        from app.workers.celery_app import create_celery_app

        celery_app = create_celery_app(self.config)
        async_result = celery_app.send_task(
            self.config.task_name,
            args=[payload],
            queue=self.config.queue_name,
        )
        return str(async_result.id)

    def _require_shared_stores(self) -> None:
        """Fail clearly when Celery would use process-local memory stores."""

        if isinstance(self.cache_store, InMemoryCacheStore) or isinstance(
            self.event_store, InMemoryEventStore
        ):
            raise RuntimeError(
                "Celery backend requires shared cache/event stores. Configure "
                f"{REDIS_URL_ENV}, use a Redis broker URL, or inject non-memory stores."
            )

    def _append_event(
        self,
        job: JobRecord,
        event_type: EventType,
        *,
        message: str,
        payload: dict[str, object],
    ) -> None:
        """Append a job-scoped event to the configured event store."""

        self.event_store.append_event(
            AgentEvent(
                event_type=event_type,
                session_id=job.session_id,
                job_id=job.job_id,
                node_name="celery_runner",
                message=message,
                payload=payload,
            )
        )

    def _save_job(self, job: JobRecord) -> JobRecord:
        """Save a job to process-local and shared cache state."""

        self._jobs[job.job_id] = job
        save_job_record(self.cache_store, job)
        return job

    def _load_state_for_job(self, job: JobRecord) -> AgentState:
        """Load the latest state from checkpoint or cached job record."""

        checkpoint = self.checkpoint_store.load_checkpoint(job.session_id, job.job_id)
        if checkpoint is not None:
            return checkpoint
        if job.final_state is not None:
            return job.final_state.model_copy(deep=True)
        raise ValueError(f"Job '{job.job_id}' has no state to resume.")

    def _require_job(self, job_id: str) -> JobRecord:
        """Return a shared job or raise a stable KeyError."""

        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        return job


def celery_store_bundle_from_env(config: CeleryRunnerConfig) -> CeleryStoreBundle:
    """Build stores suitable for API and Celery worker processes."""

    app_config = AppConfig.from_env()
    return celery_store_bundle_from_config(config, app_config)


def celery_store_bundle_from_config(
    config: CeleryRunnerConfig,
    app_config: AppConfig,
) -> CeleryStoreBundle:
    """Build shared stores from explicit runtime configuration."""

    redis_url = _redis_store_url(config, app_config)
    cache_store: CacheStore = RedisCacheStore(url=redis_url) if redis_url else InMemoryCacheStore()
    event_store: EventStore = RedisEventStore(url=redis_url) if redis_url else InMemoryEventStore()
    checkpoint_store: CheckpointStore = (
        PostgresCheckpointStore(url=app_config.effective_checkpoint_url)
        if app_config.effective_checkpoint_url
        else InMemoryCheckpointStore()
    )
    artifact_store: ArtifactStore = FileArtifactStore(root_dir=app_config.artifact_dir)
    return CeleryStoreBundle(
        cache_store=cache_store,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        artifact_store=artifact_store,
    )


def celery_submit_environment_ready(config: CeleryRunnerConfig | None = None) -> bool:
    """Return whether real Celery submission has the minimum local env."""

    active_config = config or CeleryRunnerConfig.from_env()
    return bool(active_config.broker_url and _redis_store_url(active_config, AppConfig.from_env()))


def _updated_job(job: JobRecord, **updates: object) -> JobRecord:
    """Return a JobRecord update with a refreshed timestamp."""

    return job.model_copy(update={**updates, "updated_at": utc_now()}, deep=True)


def _redis_store_url(config: CeleryRunnerConfig, app_config: AppConfig) -> str | None:
    """Return an explicit Redis store URL or reuse a Redis broker URL."""

    if app_config.effective_redis_url:
        return app_config.effective_redis_url
    broker_url = config.broker_url or ""
    if broker_url.startswith(("redis://", "rediss://", "unix://")):
        return broker_url
    return None


def _state_for_job(job: JobRecord) -> AgentState:
    """Return a mutable copy of a job state or fail with a clear error."""

    if job.final_state is None:
        raise ValueError(f"Job '{job.job_id}' has no state to resume.")
    return job.final_state.model_copy(deep=True)


__all__ = [
    "CELERY_BROKER_URL_ENV",
    "CELERY_RESULT_BACKEND_ENV",
    "CELERY_QUEUE_ENV",
    "CELERY_TASK_NAME_ENV",
    "DEFAULT_CELERY_TASK_NAME",
    "ARTIFACT_DIR_ENV",
    "CeleryRunnerConfig",
    "CeleryStoreBundle",
    "CeleryWorkerBackend",
    "TaskSubmitter",
    "celery_store_bundle_from_env",
    "celery_submit_environment_ready",
]
