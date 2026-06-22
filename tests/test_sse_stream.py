"""Tests for in-memory Server-Sent Events job streaming."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from llm import FakeLLMClient, LLMResponse
from schemas import ChartSpec, ChartType, Insight
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult


def test_sse_stream_emits_typed_json_frames_and_done(sqlite_data_source) -> None:
    """SSE endpoint should emit event names and JSON AgentEvent data."""

    client = _client(InMemoryJobRunner(data_source=sqlite_data_source))
    created_job = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    ).json()

    response = client.get(f"/jobs/{created_job['job_id']}/events/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _parse_sse(response.text)
    assert frames
    assert frames[-1]["event"] == "done"
    assert frames[-1]["data"]["event_type"] == "done"
    assert frames[-1]["data"]["job_id"] == created_job["job_id"]
    assert all("data" in frame for frame in frames)


def test_sse_stream_ends_after_done_event(sqlite_data_source) -> None:
    """Completed jobs should stream through done and then close."""

    client = _client(InMemoryJobRunner(data_source=sqlite_data_source))
    created_job = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    ).json()

    frames = _parse_sse(client.get(f"/jobs/{created_job['job_id']}/events/stream").text)

    assert frames[-1]["event"] == "done"
    assert [frame["event"] for frame in frames].count("done") == 1


def test_sse_stream_includes_stopped_after_cancel(sqlite_data_source) -> None:
    """Cancelled jobs should stream the stopped event and close."""

    client = _client(InMemoryJobRunner(data_source=sqlite_data_source))
    waiting_job = client.post(
        "/sessions/session-1/chat",
        json={
            "message": "export report",
            "command": "report",
            "analysis_package": _analysis_package().model_dump(mode="json"),
        },
    ).json()

    cancel_response = client.post(f"/jobs/{waiting_job['job_id']}/cancel")
    stream_response = client.get(f"/jobs/{waiting_job['job_id']}/events/stream")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    frames = _parse_sse(stream_response.text)
    assert frames[-1]["event"] == "stopped"
    assert any(frame["event"] == "stopped" for frame in frames)


def test_sse_stream_includes_llm_observability_events(sqlite_data_source) -> None:
    """LLM start and end diagnostics should be visible through SSE."""

    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        llm_client=FakeLLMClient(
            [
                LLMResponse(
                    content=(
                        '{"title": "LLM revenue insight", "summary": "Revenue totals 310.", '
                        '"evidence": ["total_revenue=310"], "confidence": 0.8}'
                    ),
                    model="fake-model",
                    metadata={"provider": "fake"},
                )
            ]
        ),
        node_strategies={"generate_insight": "llm"},
    )
    client = _client(runner)
    created_job = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?", "command": "analyze"},
    ).json()

    frames = _parse_sse(client.get(f"/jobs/{created_job['job_id']}/events/stream").text)
    frame_events = [frame["event"] for frame in frames]

    assert "llm_start" in frame_events
    assert "llm_end" in frame_events
    llm_end_frame = next(frame for frame in frames if frame["event"] == "llm_end")
    assert llm_end_frame["data"]["payload"]["provider"] == "fake"
    assert llm_end_frame["data"]["payload"]["model"] == "fake-model"


def test_sse_stream_sanitizes_large_artifact_payloads() -> None:
    """SSE payload encoding should omit known large artifact bodies."""

    from app.api.main import _format_sse_event
    from schemas.event import AgentEvent, EventType

    event = AgentEvent(
        event_type=EventType.CHART_REF,
        session_id="session-1",
        job_id="job-1",
        payload={"artifact_ref": "artifact:chart-1", "chart_html": "<html>large</html>"},
    )

    frame = _parse_sse(_format_sse_event(event))[0]

    assert frame["data"]["payload"]["artifact_ref"] == "artifact:chart-1"
    assert frame["data"]["payload"]["chart_html"] == "<omitted>"


def _client(runner: InMemoryJobRunner) -> TestClient:
    """Build a FastAPI test client with an injected runner."""

    return TestClient(create_app(job_runner=runner))


def _analysis_package() -> AnalysisPackage:
    """Create a package payload for report SSE tests."""

    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE, title="Total revenue"),
        insights=[
            Insight(
                title="Revenue summary",
                summary="\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002",
            )
        ],
    )


def _parse_sse(stream_text: str) -> list[dict[str, object]]:
    """Parse a small SSE response body into event and data pairs."""

    frames: list[dict[str, object]] = []
    for raw_frame in stream_text.strip().split("\n\n"):
        event_type: str | None = None
        data_payload: dict[str, object] | None = None
        for line in raw_frame.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            if line.startswith("data: "):
                data_payload = json.loads(line.removeprefix("data: "))
        if event_type is not None and data_payload is not None:
            frames.append({"event": event_type, "data": data_payload})
    return frames
