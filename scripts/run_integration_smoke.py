"""Local API integration smoke test for job, events, and artifact references."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api import create_app
from app.workers import JobStatus
from app.workers.celery_runner import celery_submit_environment_ready
from schemas._base import StrictBaseModel
from scripts.run_api import APISettings, build_runner

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_SESSION_ID = "integration-smoke"
DEFAULT_MESSAGE = "Show monthly GMV trend"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.WAITING_FOR_HUMAN.value,
}
RunnerBackendName = Literal["memory", "celery"]
DatasourceSmokeKind = Literal["sql", "file"]
FileRegistrationMode = Literal["from_path", "upload"]
EXPORT_CONFIRM_COMMANDS = ("excel_confirm", "ppt_confirm", "dashboard_confirm")


class IntegrationSmokeSettings(StrictBaseModel):
    """Local integration smoke settings."""

    api_url: str = DEFAULT_API_URL
    session_id: str = DEFAULT_SESSION_ID
    message: str = DEFAULT_MESSAGE
    runner_backend: RunnerBackendName = "memory"
    datasource_kind: DatasourceSmokeKind = "sql"
    file_registration_mode: FileRegistrationMode = "from_path"
    datasource_id: str | None = None
    file_path: str | None = None
    file_table_name: str | None = None
    profile_datasource: bool = False
    include_exploration: bool = False
    include_exports: bool = False
    in_process: bool = False
    test_sse: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse integration smoke CLI flags."""

    parser = argparse.ArgumentParser(description="Run a local API integration smoke test.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--runner-backend", choices=("memory", "celery"), default="memory")
    parser.add_argument(
        "--datasource-kind",
        choices=("sql", "file"),
        default="sql",
        help="Use the configured SQL datasource or register a local file datasource first.",
    )
    parser.add_argument(
        "--file-registration-mode",
        choices=("from_path", "upload"),
        default="from_path",
        help="Register file datasource by local path JSON endpoint or multipart upload.",
    )
    parser.add_argument("--datasource-id", default=None)
    parser.add_argument("--file-path", default=None)
    parser.add_argument("--file-table-name", default=None)
    parser.add_argument(
        "--profile-datasource",
        action="store_true",
        help="Profile the selected datasource before direct analysis.",
    )
    parser.add_argument(
        "--include-exploration",
        action="store_true",
        help="Also run an open exploration job.",
    )
    parser.add_argument(
        "--include-exports",
        action="store_true",
        help="Also smoke report outline plus excel/ppt/dashboard confirm fast-paths.",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Run FastAPI app in-process with the selected runner instead of HTTP.",
    )
    parser.add_argument("--sse", action="store_true", help="Fetch SSE events after submit.")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> IntegrationSmokeSettings:
    """Convert CLI args to IntegrationSmokeSettings."""

    return IntegrationSmokeSettings(
        api_url=args.api_url.rstrip("/"),
        session_id=args.session_id,
        message=args.message,
        runner_backend=args.runner_backend,
        datasource_kind=args.datasource_kind,
        file_registration_mode=args.file_registration_mode,
        datasource_id=args.datasource_id,
        file_path=args.file_path,
        file_table_name=args.file_table_name,
        profile_datasource=args.profile_datasource,
        include_exploration=args.include_exploration,
        include_exports=args.include_exports,
        in_process=args.in_process,
        test_sse=args.sse,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )


def build_chat_payload(settings: IntegrationSmokeSettings) -> dict[str, Any]:
    """Build the chat request payload for direct analysis smoke."""

    return {
        "message": settings.message,
        "command": "none",
    }


def setup_datasource_if_requested(
    client: SmokeClient,
    settings: IntegrationSmokeSettings,
) -> dict[str, Any] | None:
    """Optionally register a file datasource and attach it to the smoke session."""

    if settings.datasource_kind != "file":
        return None
    if not settings.file_path:
        raise ValueError("--file-path is required when --datasource-kind=file.")
    datasource_id = settings.datasource_id or f"file-smoke-{int(time.time())}"
    if settings.file_registration_mode == "upload":
        record = client.post_multipart(
            "/datasources/upload",
            fields={
                "datasource_id": datasource_id,
                "name": datasource_id,
                "table_name": settings.file_table_name or "",
            },
            file_field="file",
            file_path=Path(settings.file_path),
        )
    else:
        record = client.post(
            "/datasources/from-path",
            {
                "datasource_id": datasource_id,
                "name": datasource_id,
                "path": settings.file_path,
                "table_name": settings.file_table_name,
            },
        )
    selected = client.post(
        f"/sessions/{settings.session_id}/datasource",
        {"datasource_id": datasource_id},
    )
    return {
        "datasource": _datasource_summary(record),
        "session_datasource": selected.get("datasource_id"),
    }


def run_profile_smoke(
    client: SmokeClient,
    settings: IntegrationSmokeSettings,
    datasource_id: str | None,
) -> dict[str, Any] | None:
    """Optionally profile the selected datasource before analysis."""

    if not settings.profile_datasource or not datasource_id:
        return None
    profile_job = client.post(f"/datasources/{datasource_id}/profile", {})
    return poll_job(
        client,
        profile_job["job_id"],
        timeout_seconds=settings.timeout_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
    )


def run_open_exploration_smoke(
    client: SmokeClient,
    settings: IntegrationSmokeSettings,
) -> dict[str, Any] | None:
    """Optionally run the open exploration graph."""

    if not settings.include_exploration:
        return None
    exploration_job = client.post(
        f"/sessions/{settings.session_id}/chat",
        {"message": "Explore this datasource", "command": "explore"},
    )
    return poll_job(
        client,
        exploration_job["job_id"],
        timeout_seconds=settings.timeout_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
    )


def run_export_fast_path_smoke(
    client: SmokeClient,
    settings: IntegrationSmokeSettings,
    final_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Optionally smoke report outline plus export confirm commands."""

    if not settings.include_exports:
        return []
    analysis_package = final_state.get("analysis_package")
    if not analysis_package:
        return []
    export_jobs: list[dict[str, Any]] = []
    for command in EXPORT_CONFIRM_COMMANDS:
        outline_job = client.post(
            f"/sessions/{settings.session_id}/chat",
            {
                "message": f"Prepare {command} export outline",
                "command": "report",
                "analysis_package": analysis_package,
            },
        )
        outline_job = poll_job(
            client,
            outline_job["job_id"],
            timeout_seconds=settings.timeout_seconds,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
        confirmed_job = client.post(
            f"/jobs/{outline_job['job_id']}/approve",
            {"command": command},
        )
        confirmed_job = poll_job(
            client,
            confirmed_job["job_id"],
            timeout_seconds=settings.timeout_seconds,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
        export_jobs.append(confirmed_job)
    return export_jobs


def _selected_datasource_id(
    settings: IntegrationSmokeSettings,
    datasource_setup: dict[str, Any] | None,
) -> str | None:
    """Return the datasource id used by this smoke run."""

    if datasource_setup:
        return datasource_setup.get("session_datasource")
    return settings.datasource_id


def run_smoke(settings: IntegrationSmokeSettings) -> dict[str, Any]:
    """Run one integration smoke test and return printable summary data."""

    if settings.runner_backend == "celery" and not celery_submit_environment_ready():
        return {
            "runner_backend": settings.runner_backend,
            "status": "skipped",
            "message": (
                "Celery smoke requires DATA_ANALYSIS_AGENT_CELERY_BROKER_URL and shared "
                "Redis stores through DATA_ANALYSIS_AGENT_REDIS_URL or a Redis broker URL."
            ),
            "diagnostics": celery_diagnostics(),
        }

    client = _client_for_settings(settings)
    datasource_setup = setup_datasource_if_requested(client, settings)
    selected_datasource_id = _selected_datasource_id(settings, datasource_setup)
    profile_job = run_profile_smoke(client, settings, selected_datasource_id)
    created_job = client.post(
        f"/sessions/{settings.session_id}/chat",
        build_chat_payload(settings),
    )
    job_id = created_job["job_id"]
    final_job = poll_job(
        client,
        job_id,
        timeout_seconds=settings.timeout_seconds,
        poll_interval_seconds=settings.poll_interval_seconds,
    )
    events = client.get(f"/jobs/{job_id}/events")
    sse_events = client.get_sse(f"/jobs/{job_id}/events/stream") if settings.test_sse else []
    final_state = final_job.get("final_state") or {}
    exploration_job = run_open_exploration_smoke(client, settings)
    export_jobs = run_export_fast_path_smoke(client, settings, final_state)
    artifact_refs = artifact_refs_from_state(final_state)
    for export_job in export_jobs:
        artifact_refs.extend(artifact_refs_from_state(export_job.get("final_state") or {}))
    artifact_refs = _deduplicate(artifact_refs)
    return {
        "runner_backend": settings.runner_backend,
        "datasource_setup": datasource_setup,
        "profile_job": _job_summary(profile_job) if profile_job else None,
        "job": _job_summary(final_job),
        "exploration_job": _job_summary(exploration_job) if exploration_job else None,
        "export_jobs": [_job_summary(job) for job in export_jobs],
        "final_state": _final_state_summary(final_state),
        "artifact_refs": artifact_refs,
        "artifact_checks": artifact_checks(client, artifact_refs),
        "event_count": len(events),
        "event_types": [event["event_type"] for event in events],
        "sse_event_count": len(sse_events),
        "sse_event_types": [event["event"] for event in sse_events],
    }


def poll_job(
    client: SmokeClient,
    job_id: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """Poll job status until terminal or timeout."""

    deadline = time.monotonic() + timeout_seconds
    latest_job = client.get(f"/jobs/{job_id}")
    while latest_job["status"] not in TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        latest_job = client.get(f"/jobs/{job_id}")
    return latest_job


def artifact_refs_from_state(final_state: dict[str, Any]) -> list[str]:
    """Collect artifact refs from final state without reading artifact content."""

    refs: list[str] = []
    chart_spec = final_state.get("chart_spec") or {}
    if chart_spec.get("artifact_ref"):
        refs.append(chart_spec["artifact_ref"])
    analysis_package = final_state.get("analysis_package") or {}
    refs.extend(analysis_package.get("artifact_refs") or [])
    report_result = final_state.get("report_result") or {}
    if report_result.get("artifact_ref"):
        refs.append(report_result["artifact_ref"])
    return _deduplicate(refs)


def artifact_checks(client: SmokeClient, artifact_refs: list[str]) -> list[dict[str, Any]]:
    """Fetch artifact metadata/content sizes without printing artifact bodies."""

    checks: list[dict[str, Any]] = []
    for artifact_ref in artifact_refs:
        artifact_id = artifact_ref.split(":", maxsplit=1)[-1]
        metadata = client.get(f"/artifacts/{artifact_id}")
        content = client.get_content(f"/artifacts/{artifact_id}/content")
        checks.append(
            {
                "artifact_ref": artifact_ref,
                "mime_type": metadata.get("mime_type"),
                "metadata_available": True,
                "content_bytes": len(content),
            }
        )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for local integration smoke."""

    settings = settings_from_args(parse_args(argv))
    print(json.dumps(run_smoke(settings), indent=2, sort_keys=True, default=str))
    return 0


class SmokeClient:
    """Small client abstraction shared by HTTP and in-process smoke modes."""

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and return JSON response."""

        raise NotImplementedError

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> dict[str, Any]:
        """POST multipart form data and return JSON response."""

        raise NotImplementedError

    def get(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        """GET JSON and return JSON response."""

        raise NotImplementedError

    def get_sse(self, path: str) -> list[dict[str, Any]]:
        """Fetch SSE frames and return parsed event metadata."""

        raise NotImplementedError

    def get_content(self, path: str) -> bytes:
        """GET raw response content."""

        raise NotImplementedError


class HTTPSmokeClient(SmokeClient):
    """urllib-based client for a running local FastAPI app."""

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to a running API."""

        request = Request(
            f"{self.api_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return _read_json_response(request)

    def get(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        """GET JSON from a running API."""

        return _read_json_response(Request(f"{self.api_url}{path}", method="GET"))

    def get_sse(self, path: str) -> list[dict[str, Any]]:
        """Fetch finite SSE frames from a running API."""

        request = Request(
            f"{self.api_url}{path}",
            headers={"Accept": "text/event-stream"},
            method="GET",
        )
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return _parse_sse_text(response.read().decode("utf-8"))

    def get_content(self, path: str) -> bytes:
        """Fetch raw content from a running API."""

        request = Request(f"{self.api_url}{path}", method="GET")
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read()

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> dict[str, Any]:
        """POST multipart form data to a running API."""

        body, content_type = _multipart_body(fields, file_field=file_field, file_path=file_path)
        request = Request(
            f"{self.api_url}{path}",
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        return _read_json_response(request)


class InProcessSmokeClient(SmokeClient):
    """FastAPI TestClient-based smoke client for local memory/celery skeletons."""

    def __init__(self, settings: IntegrationSmokeSettings) -> None:
        from fastapi.testclient import TestClient

        config = APISettings().app_config.with_overrides(
            runner_backend=settings.runner_backend,
            allow_local_file_paths=settings.datasource_kind == "file",
            upload_dir=str(ROOT_DIR / "runtime" / "integration_uploads"),
        )
        api_settings = APISettings(
            app_config=config,
            runner_backend=settings.runner_backend,
        )
        self.client = TestClient(create_app(job_runner=build_runner(api_settings)))

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON through TestClient."""

        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def get(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        """GET JSON through TestClient."""

        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def get_sse(self, path: str) -> list[dict[str, Any]]:
        """Fetch finite SSE frames through TestClient."""

        response = self.client.get(path)
        response.raise_for_status()
        return _parse_sse_text(response.text)

    def get_content(self, path: str) -> bytes:
        """Fetch raw content through TestClient."""

        response = self.client.get(path)
        response.raise_for_status()
        return response.content

    def post_multipart(
        self,
        path: str,
        *,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
    ) -> dict[str, Any]:
        """POST multipart form data through TestClient."""

        data = {key: value for key, value in fields.items() if value}
        with file_path.open("rb") as handle:
            response = self.client.post(
                path,
                data=data,
                files={
                    file_field: (
                        file_path.name,
                        handle,
                        mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
                    )
                },
            )
        response.raise_for_status()
        return response.json()


def _client_for_settings(settings: IntegrationSmokeSettings) -> SmokeClient:
    """Return HTTP or in-process smoke client."""

    if settings.in_process:
        return InProcessSmokeClient(settings)
    return HTTPSmokeClient(settings.api_url)


def _read_json_response(request: Request) -> dict[str, Any] | list[dict[str, Any]]:
    """Open a urllib request and decode JSON, preserving HTTP error details."""

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            "Could not reach the API. Start scripts/run_api.py or docker compose first. "
            f"Original error: {exc.reason}"
        ) from exc


def _multipart_body(
    fields: dict[str, str],
    *,
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    """Build a small multipart body for stdlib HTTP smoke calls."""

    if not file_path.is_file():
        raise FileNotFoundError(f"File datasource path does not exist: {file_path}")
    boundary = f"----daa-smoke-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if not value:
            continue
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def celery_diagnostics() -> dict[str, object]:
    """Return human-readable Celery/Docker readiness hints without starting services."""

    return {
        "docker_cli_found": shutil.which("docker") is not None,
        "requires": [
            "DATA_ANALYSIS_AGENT_CELERY_BROKER_URL",
            "DATA_ANALYSIS_AGENT_REDIS_URL or redis broker URL",
            "shared DATA_ANALYSIS_AGENT_ARTIFACT_DIR",
            "shared DATA_ANALYSIS_AGENT_UPLOAD_DIR",
        ],
        "hint": (
            "Run docker compose -f docker-compose.celery.yml up --build, then retry "
            "the smoke command with --api-url http://127.0.0.1:8000 --runner-backend celery."
        ),
    }


def _parse_sse_text(text: str) -> list[dict[str, Any]]:
    """Parse a small finite SSE response into event/data dictionaries."""

    frames: list[dict[str, Any]] = []
    for raw_frame in text.strip().split("\n\n"):
        if not raw_frame:
            continue
        event_name = "message"
        data = ""
        for line in raw_frame.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        frames.append({"event": event_name, "data": json.loads(data) if data else None})
    return frames


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Return a compact job summary for smoke output."""

    return {
        "job_id": job.get("job_id"),
        "session_id": job.get("session_id"),
        "status": job.get("status"),
        "intent": job.get("intent"),
        "command": job.get("command"),
        "final_response_text": job.get("final_response_text"),
        "error_message": job.get("error_message"),
    }


def _datasource_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Return datasource metadata without local paths or file contents."""

    return {
        "datasource_id": record.get("datasource_id"),
        "kind": record.get("kind"),
        "status": record.get("status"),
        "original_filename": record.get("original_filename"),
        "table_name": record.get("table_name"),
        "row_count": record.get("row_count"),
        "columns": record.get("columns"),
    }


def _final_state_summary(final_state: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded final state summary without large artifact content."""

    return {
        "intent": final_state.get("intent"),
        "command": final_state.get("command"),
        "sql": (final_state.get("sql_draft") or {}).get("query"),
        "chart_type": (final_state.get("chart_spec") or {}).get("chart_type"),
        "chart_artifact_ref": (final_state.get("chart_spec") or {}).get("artifact_ref"),
        "analysis_package_id": (final_state.get("analysis_package") or {}).get("package_id"),
        "final_response_text": final_state.get("final_response_text"),
        "error_count": final_state.get("error_count"),
    }


def _deduplicate(values: list[str]) -> list[str]:
    """Deduplicate refs while preserving order."""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
