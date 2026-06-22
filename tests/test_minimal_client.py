"""Tests for minimal API client request and demo-flow helpers."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.api.schemas import JobResponse
from app.harness import build_initial_state
from app.workers import InMemoryJobRunner
from examples.client import demo_flow_client, minimal_client
from examples.client.minimal_client import DataAnalysisAPIClient, approve_hint
from schemas.analysis_package import AnalysisPackage
from schemas.report import ReportOutline
from scripts.create_demo_db import create_demo_data_source


class FakeResponse:
    """Small context-manager response used instead of a real HTTP server."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeResponse:
        """Return the fake response."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """No cleanup needed."""

    def read(self) -> bytes:
        """Return response bytes."""

        return self.body


def test_minimal_client_sends_chat_approve_cancel_and_artifact_requests(monkeypatch) -> None:
    """Client methods should call the documented endpoints with JSON payloads."""

    requests = []
    responses = [
        {"job_id": "job-1"},
        {"job_id": "job-1", "status": "completed"},
        {"job_id": "job-1", "status": "cancelled"},
        {"artifact_id": "artifact-1", "artifact_ref": "artifact:artifact-1"},
        b"artifact-body",
    ]

    def fake_urlopen(request, timeout: float):
        requests.append((request, timeout))
        response = responses.pop(0)
        body = response if isinstance(response, bytes) else json.dumps(response).encode("utf-8")
        return FakeResponse(body)

    monkeypatch.setattr(minimal_client, "urlopen", fake_urlopen)
    client = DataAnalysisAPIClient(base_url="http://api.local", timeout_seconds=5)

    created = client.post_chat(
        session_id="session-1",
        message="Show monthly GMV trend",
        command="none",
        datasource_id="demo",
    )
    approved = client.approve("job-1", "excel_confirm")
    cancelled = client.cancel("job-1")
    metadata = client.get_artifact_metadata("artifact:file:artifact-1")
    content = client.get_artifact_content("artifact:file:artifact-1")

    assert created["job_id"] == "job-1"
    assert approved["status"] == "completed"
    assert cancelled["status"] == "cancelled"
    assert metadata["artifact_ref"] == "artifact:artifact-1"
    assert content == b"artifact-body"
    assert [request.get_method() for request, _ in requests] == [
        "POST",
        "POST",
        "POST",
        "GET",
        "GET",
    ]
    assert requests[0][0].full_url == "http://api.local/sessions/session-1/chat"
    assert requests[0][0].headers["Content-type"] == "application/json; charset=utf-8"
    assert json.loads(requests[0][0].data.decode("utf-8")) == {
        "message": "Show monthly GMV trend",
        "command": "none",
        "datasource_id": "demo",
    }
    assert requests[3][0].full_url == "http://api.local/artifacts/artifact-1"
    assert requests[4][0].full_url == "http://api.local/artifacts/artifact-1/content"


def test_minimal_client_sends_chinese_message_as_utf8_json(monkeypatch) -> None:
    """minimal_client 发送中文 message 时请求体应是 UTF-8 JSON 且可无损解析。"""

    requests = []

    def fake_urlopen(request, timeout: float):
        requests.append((request, timeout))
        return FakeResponse(json.dumps({"job_id": "job-cn"}).encode("utf-8"))

    monkeypatch.setattr(minimal_client, "urlopen", fake_urlopen)
    client = DataAnalysisAPIClient(base_url="http://api.local", timeout_seconds=5)
    message = "近 12 个月销售趋势怎么样？"

    created = client.post_chat(session_id="session-cn", message=message)

    assert created["job_id"] == "job-cn"
    request = requests[0][0]
    assert request.headers["Content-type"] == "application/json; charset=utf-8"
    assert message.encode("utf-8") in request.data
    assert json.loads(request.data.decode("utf-8"))["message"] == message


def test_minimal_client_approve_hint_for_human_request() -> None:
    """Waiting jobs should produce a concrete approve example."""

    job = {
        "job_id": "job-1",
        "final_state": {
            "human_request": {
                "request_type": "report_confirm",
                "options": [{"value": "excel_confirm"}],
            }
        },
    }

    assert approve_hint(job) == "client.approve('job-1', 'excel_confirm')"


def test_demo_flow_client_uses_existing_analysis_package_and_downloads_artifacts(
    monkeypatch,
) -> None:
    """Demo flow should compose API calls without requiring a real API server."""

    fake_client = FakeDemoClient()
    monkeypatch.setattr(demo_flow_client, "DataAnalysisAPIClient", lambda base_url: fake_client)

    settings = demo_flow_client.parse_args(
        ["--base-url", "http://api.local", "--confirm-command", "excel_confirm"]
    )
    summary = demo_flow_client.run_demo_flow(settings)

    assert fake_client.chat_commands == ["none", "report"]
    assert fake_client.approvals == [("job-report", "excel_confirm")]
    assert summary["direct_analysis"]["job_id"] == "job-direct"
    assert summary["report_outline"]["approve_hint"] == (
        "client.approve('job-report', 'excel_confirm')"
    )
    assert summary["confirmed_export"]["job_id"] == "job-export"
    assert summary["artifact_refs"] == ["artifact:chart-1", "artifact:excel-1"]
    assert summary["downloads"] == [
        {
            "artifact_ref": "artifact:chart-1",
            "artifact_id": "chart-1",
            "mime_type": "application/json",
            "metadata_keys": ["artifact_kind"],
            "content_bytes": 15,
        },
        {
            "artifact_ref": "artifact:excel-1",
            "artifact_id": "excel-1",
            "mime_type": "application/octet-stream",
            "metadata_keys": ["report_type"],
            "content_bytes": 15,
        },
    ]


@pytest.mark.parametrize(
    "confirm_command",
    ["dashboard_confirm", "excel_confirm", "ppt_confirm", "report_confirm"],
)
def test_demo_flow_client_confirm_commands_complete_with_fast_path(
    monkeypatch,
    confirm_command: str,
) -> None:
    """demo_flow_client should approve the waiting job and reuse its saved outline."""

    client = InProcessDemoClient()
    monkeypatch.setattr(demo_flow_client, "DataAnalysisAPIClient", lambda base_url: client)
    settings = demo_flow_client.parse_args(
        ["--base-url", "http://api.local", "--confirm-command", confirm_command]
    )

    summary = demo_flow_client.run_demo_flow(settings)

    assert summary["direct_analysis"]["status"] == "completed"
    assert summary["report_outline"]["status"] == "waiting_for_human"
    assert "done" not in summary["report_outline"]["event_types"]
    assert "error" not in summary["report_outline"]["event_types"]
    assert summary["report_outline"]["approve_hint"].endswith(f", '{confirm_command}')")
    assert summary["confirmed_export"]["status"] == "completed"
    assert summary["confirmed_export"]["command"] == confirm_command
    assert summary["confirmed_export"]["error_message"] is None
    assert summary["confirmed_export"]["artifact_refs"]
    assert len(summary["downloads"]) >= 2

    report_job_id = summary["report_outline"]["job_id"]
    events = client.list_events(report_job_id)
    event_types = [event["event_type"] for event in events]
    generate_outline_events = [
        event for event in events if event.get("node_name") == "generate_outline"
    ]
    assert len(generate_outline_events) == 2
    assert event_types.count("human_request") == 1
    assert event_types.count("done") == 1
    assert any(event["event_type"] == "artifact_ref" for event in events)
    assert all(event["event_type"] != "error" for event in events)


class FakeDemoClient:
    """Fake API client used to test demo_flow_client without network."""

    def __init__(self) -> None:
        self.chat_commands: list[str] = []
        self.approvals: list[tuple[str, str]] = []

    def post_chat(self, **kwargs) -> dict[str, Any]:
        """Return a submitted job based on command."""

        command = kwargs["command"]
        self.chat_commands.append(command)
        if command == "none":
            return {"job_id": "job-direct"}
        return {"job_id": "job-report"}

    def wait_for_job(self, job_id: str) -> dict[str, Any]:
        """Return terminal job snapshots."""

        if job_id == "job-direct":
            return {
                "job_id": "job-direct",
                "status": "completed",
                "intent": "direct_analysis",
                "command": "analyze",
                "final_response_text": "Analysis complete.",
                "final_state": {
                    "analysis_package": {
                        "package_id": "package-1",
                        "artifact_refs": ["artifact:chart-1"],
                    },
                    "chart_spec": {"artifact_ref": "artifact:chart-1"},
                },
            }
        if job_id == "job-report":
            return {
                "job_id": "job-report",
                "status": "waiting_for_human",
                "intent": "report_export",
                "command": "report",
                "final_state": {
                    "human_request": {
                        "request_type": "report_confirm",
                        "options": [{"value": "excel_confirm"}],
                    }
                },
            }
        return {
            "job_id": "job-export",
            "status": "completed",
            "intent": "report_export",
            "command": "excel_confirm",
            "final_response_text": "Export complete.",
            "final_state": {
                "report_result": {"artifact_ref": "artifact:excel-1"},
            },
        }

    def approve(self, job_id: str, command: str) -> dict[str, Any]:
        """Record approval and return a submitted export job."""

        self.approvals.append((job_id, command))
        return {"job_id": "job-export"}

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return lightweight event metadata."""

        return [{"event_type": "done", "job_id": job_id}]

    def download_artifact(self, artifact_ref: str):
        """Return fake artifact downloads with byte-sized bodies."""

        if artifact_ref == "artifact:chart-1":
            return minimal_client.ArtifactDownload(
                artifact_ref="artifact:chart-1",
                metadata={
                    "mime_type": "application/json",
                    "metadata": {"artifact_kind": "chart"},
                },
                content=b'{"chart": true}',
                content_type="application/json",
            )
        return minimal_client.ArtifactDownload(
            artifact_ref="artifact:excel-1",
            metadata={
                "mime_type": "application/octet-stream",
                "metadata": {"report_type": "excel"},
            },
            content=b"fake-excel-body",
            content_type="application/octet-stream",
        )


class InProcessDemoClient:
    """API-client replacement that exercises the real in-memory runner."""

    def __init__(self) -> None:
        self.runner = InMemoryJobRunner(data_source=create_demo_data_source())

    def post_chat(self, **kwargs) -> dict[str, Any]:
        """Submit a job through the same initial-state path as the API."""

        state = build_initial_state(
            session_id=kwargs["session_id"],
            user_message=kwargs["message"],
            command=kwargs.get("command", "none"),
            datasource_id=kwargs.get("datasource_id"),
            analysis_package=_analysis_package_from_payload(kwargs.get("analysis_package")),
            report_outline=_report_outline_from_payload(kwargs.get("report_outline")),
        )
        return _job_response(self.runner.submit_job(state))

    def wait_for_job(self, job_id: str) -> dict[str, Any]:
        """Return the latest job response."""

        record = self.runner.get_job(job_id)
        if record is None:
            raise KeyError(job_id)
        return _job_response(record)

    def approve(self, job_id: str, command: str) -> dict[str, Any]:
        """Approve the existing waiting job."""

        return _job_response(self.runner.approve(job_id, command))

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return serialized events."""

        return [event.model_dump(mode="json") for event in self.runner.list_events(job_id)]

    def download_artifact(self, artifact_ref: str):
        """Return artifact metadata and byte content from the runner store."""

        metadata = self.runner.artifact_store.get_artifact_metadata(artifact_ref)
        content = self.runner.artifact_store.get_artifact_content(artifact_ref)
        if metadata is None or content is None:
            raise KeyError(artifact_ref)
        return minimal_client.ArtifactDownload(
            artifact_ref=metadata.artifact_ref,
            metadata={
                "mime_type": metadata.mime_type,
                "metadata": metadata.metadata,
            },
            content=_artifact_content_bytes(content),
            content_type=metadata.mime_type,
        )


def _analysis_package_from_payload(payload: dict[str, Any] | None) -> AnalysisPackage | None:
    """Validate serialized AnalysisPackage payloads passed by demo_flow_client."""

    return None if payload is None else AnalysisPackage.model_validate(payload)


def _report_outline_from_payload(payload: dict[str, Any] | None) -> ReportOutline | None:
    """Validate serialized ReportOutline payloads passed by demo_flow_client."""

    return None if payload is None else ReportOutline.model_validate(payload)


def _job_response(record) -> dict[str, Any]:
    """Serialize a JobRecord the same way the FastAPI response model does."""

    return JobResponse.from_record(record).model_dump(mode="json")


def _artifact_content_bytes(content: Any) -> bytes:
    """Convert artifact API content to bytes for the client download summary."""

    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return json.dumps(content, ensure_ascii=False).encode("utf-8")
