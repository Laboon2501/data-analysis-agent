"""Minimal stdlib API client for local frontend/backend integration checks."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "waiting_for_human"}


@dataclass(frozen=True)
class ArtifactDownload:
    """Artifact body returned by the API without writing it into event history."""

    artifact_ref: str
    metadata: dict[str, Any]
    content: bytes
    content_type: str | None


class DataAnalysisAPIClient:
    """Small blocking client for the current FastAPI contract."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post_chat(
        self,
        *,
        session_id: str,
        message: str,
        command: str = "none",
        datasource_id: str | None = None,
        analysis_package: dict[str, Any] | None = None,
        report_outline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one chat job."""

        payload: dict[str, Any] = {
            "message": message,
            "command": command,
        }
        if datasource_id is not None:
            payload["datasource_id"] = datasource_id
        if analysis_package is not None:
            payload["analysis_package"] = analysis_package
        if report_outline is not None:
            payload["report_outline"] = report_outline
        return self._request_json("POST", f"/sessions/{session_id}/chat", payload=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return one job status."""

        return self._request_json("GET", f"/jobs/{job_id}")

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return recorded events as a finite list."""

        events = self._request_json("GET", f"/jobs/{job_id}/events")
        if not isinstance(events, list):
            raise RuntimeError("Expected event list response.")
        return events

    def stream_events(self, job_id: str) -> list[dict[str, Any]]:
        """Fetch the finite SSE stream and parse frames."""

        request = Request(
            f"{self.base_url}/jobs/{job_id}/events/stream",
            headers={"Accept": "text/event-stream"},
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            text = response.read().decode("utf-8")
        return parse_sse_frames(text)

    def approve(self, job_id: str, command: str) -> dict[str, Any]:
        """Send a confirm command such as ppt_confirm or excel_confirm."""

        return self._request_json("POST", f"/jobs/{job_id}/approve", payload={"command": command})

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Request job cancellation."""

        return self._request_json("POST", f"/jobs/{job_id}/cancel")

    def get_artifact_metadata(self, artifact_ref_or_id: str) -> dict[str, Any]:
        """Return artifact metadata by artifact id or ref."""

        artifact_id = artifact_id_from_ref(artifact_ref_or_id)
        return self._request_json("GET", f"/artifacts/{artifact_id}")

    def get_artifact_content(self, artifact_ref_or_id: str) -> bytes:
        """Return raw artifact content bytes by artifact id or ref."""

        artifact_id = artifact_id_from_ref(artifact_ref_or_id)
        request = Request(f"{self.base_url}/artifacts/{artifact_id}/content", method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()

    def download_artifact(self, artifact_ref_or_id: str) -> ArtifactDownload:
        """Download artifact metadata and body through the artifact API."""

        metadata = self.get_artifact_metadata(artifact_ref_or_id)
        content = self.get_artifact_content(artifact_ref_or_id)
        return ArtifactDownload(
            artifact_ref=normalize_artifact_ref(metadata.get("artifact_ref") or artifact_ref_or_id),
            metadata=metadata,
            content=content,
            content_type=metadata.get("mime_type"),
        )

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float = 0.5,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Poll one job until terminal status or timeout."""

        deadline = time.monotonic() + timeout_seconds
        latest_job = self.get_job(job_id)
        while latest_job.get("status") not in TERMINAL_STATUSES and time.monotonic() < deadline:
            time.sleep(poll_interval_seconds)
            latest_job = self.get_job(job_id)
        return latest_job

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Send a JSON request and decode the JSON response."""

        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def parse_sse_frames(text: str) -> list[dict[str, Any]]:
    """Parse Server-Sent Event frames into typed dictionaries."""

    frames: list[dict[str, Any]] = []
    for raw_frame in text.replace("\r\n", "\n").strip().split("\n\n"):
        if not raw_frame:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in raw_frame.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        raw_data = "\n".join(data_lines)
        frames.append(
            {
                "event": event_name,
                "data": json.loads(raw_data) if raw_data else None,
            }
        )
    return frames


def artifact_id_from_ref(artifact_ref_or_id: str) -> str:
    """Return the artifact id portion from a raw id or artifact reference."""

    value = artifact_ref_or_id.strip()
    if not value:
        raise ValueError("Artifact id/ref cannot be blank.")
    return value.rsplit(":", maxsplit=1)[-1]


def normalize_artifact_ref(artifact_ref_or_id: str) -> str:
    """Return a display-safe artifact:<id> reference."""

    return f"artifact:{artifact_id_from_ref(artifact_ref_or_id)}"


def extract_artifact_refs_from_payload(payload: Any) -> list[str]:
    """Recursively collect artifact refs from API state/event payloads."""

    refs: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"artifact_ref", "chart_artifact_ref"} and isinstance(value, str):
                refs.append(normalize_artifact_ref(value))
            elif key == "artifact_id" and isinstance(value, str):
                refs.append(normalize_artifact_ref(value))
            else:
                refs.extend(extract_artifact_refs_from_payload(value))
    elif isinstance(payload, list):
        for item in payload:
            refs.extend(extract_artifact_refs_from_payload(item))
    return deduplicate(refs)


def extract_artifact_refs_from_job(job: dict[str, Any]) -> list[str]:
    """Collect artifact refs from a job response without reading artifact bodies."""

    refs = extract_artifact_refs_from_payload(job.get("final_state") or {})
    return deduplicate(refs)


def human_request_from_job(job: dict[str, Any]) -> dict[str, Any] | None:
    """Return a structured human request when the job is waiting for approval."""

    final_state = job.get("final_state") or {}
    human_request = final_state.get("human_request")
    return human_request if isinstance(human_request, dict) else None


def approve_hint(job: dict[str, Any]) -> str | None:
    """Return a concise approve example for human_request jobs."""

    human_request = human_request_from_job(job)
    if human_request is None:
        return None
    options = human_request.get("options") or []
    command = (
        _first_confirm_command(options) or human_request.get("request_type") or "report_confirm"
    )
    return f"client.approve({job['job_id']!r}, {command!r})"


def deduplicate(values: Iterable[str]) -> list[str]:
    """Deduplicate string values while preserving order."""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _first_confirm_command(options: Any) -> str | None:
    """Return the first confirm-like command from a HumanRequest option list."""

    if not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, dict):
            value = option.get("value") or option.get("command")
            if isinstance(value, str) and value.endswith("_confirm"):
                return value
        elif isinstance(option, str) and option.endswith("_confirm"):
            return option
    return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse minimal client CLI arguments."""

    parser = argparse.ArgumentParser(description="Run a minimal Data Analysis Agent API client.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--session-id", default="client-example")
    parser.add_argument("--message", default="Show monthly GMV trend")
    parser.add_argument("--command", default="none")
    parser.add_argument("--stream", action="store_true", help="Fetch SSE events after submit.")
    parser.add_argument("--cancel", action="store_true", help="Submit then cancel the job.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Small command-line smoke that exercises the core API surface."""

    args = parse_args(argv)
    client = DataAnalysisAPIClient(base_url=args.base_url)
    created_job = client.post_chat(
        session_id=args.session_id,
        message=args.message,
        command=args.command,
    )
    job_id = created_job["job_id"]
    final_job = client.cancel(job_id) if args.cancel else client.wait_for_job(job_id)
    events = client.list_events(job_id)
    sse_events = client.stream_events(job_id) if args.stream and not args.cancel else []
    artifact_refs = extract_artifact_refs_from_job(final_job)
    hint = approve_hint(final_job)
    print(
        json.dumps(
            {
                "job_id": job_id,
                "status": final_job.get("status"),
                "final_response_text": final_job.get("final_response_text"),
                "event_types": [event.get("event_type") for event in events],
                "sse_event_types": [event.get("event") for event in sse_events],
                "artifact_refs": artifact_refs,
                "approve_hint": hint,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
