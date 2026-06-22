"""Tests for artifact metadata and content API endpoints."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from persistence import InMemoryArtifactStore
from tools.chart_tools import CHART_MIME_TYPE


def test_artifact_metadata_endpoint_returns_chart_metadata(sqlite_data_source) -> None:
    """Artifact metadata should be readable by artifact_id."""

    client, job = _client_and_completed_chart_job(sqlite_data_source)
    artifact_id = _chart_artifact_id(job)

    response = client.get(f"/artifacts/{artifact_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_id"] == artifact_id
    assert payload["artifact_ref"] == job["final_state"]["chart_spec"]["artifact_ref"]
    assert payload["mime_type"] == CHART_MIME_TYPE
    assert payload["content_type"] == "json"
    assert payload["metadata"]["artifact_kind"] == "chart"
    assert payload["metadata"]["chart_type"] == "line"
    assert "content" not in payload


def test_artifact_content_endpoint_returns_chart_content_with_mime_type(sqlite_data_source) -> None:
    """Artifact content should be returned only through the content endpoint."""

    client, job = _client_and_completed_chart_job(sqlite_data_source)
    artifact_id = _chart_artifact_id(job)

    response = client.get(f"/artifacts/{artifact_id}/content")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(CHART_MIME_TYPE)
    payload = response.json()
    assert payload["kind"] == "chart_artifact"
    assert payload["mime_type"] == CHART_MIME_TYPE
    assert payload["chart"]["chart_type"] == "line"
    assert payload["data"]["rows"] == [
        {"month": "2026-01", "total_revenue": 100.0},
        {"month": "2026-02", "total_revenue": 210.0},
    ]


def test_unknown_artifact_returns_404(sqlite_data_source) -> None:
    """Unknown artifact ids should return 404 for metadata and content."""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))

    metadata_response = client.get("/artifacts/missing-artifact")
    content_response = client.get("/artifacts/missing-artifact/content")

    assert metadata_response.status_code == 404
    assert content_response.status_code == 404


def test_chart_artifact_body_stays_out_of_events(sqlite_data_source) -> None:
    """Chart artifact body should be fetched through artifact API, not event history."""

    client, job = _client_and_completed_chart_job(sqlite_data_source)
    artifact_id = _chart_artifact_id(job)

    events_response = client.get(f"/jobs/{job['job_id']}/events")
    content_response = client.get(f"/artifacts/{artifact_id}/content")

    assert content_response.status_code == 200
    serialized_events = json.dumps(events_response.json(), sort_keys=True)
    assert "chart_ref" in serialized_events
    assert '"kind": "chart_artifact"' not in serialized_events
    assert '"rows"' not in serialized_events
    assert "2026-01" not in serialized_events


def _client_and_completed_chart_job(sqlite_data_source) -> tuple[TestClient, dict]:
    """Run a direct analysis job that creates a chart artifact."""

    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        artifact_store=InMemoryArtifactStore(),
    )
    client = TestClient(create_app(job_runner=runner))
    job = client.post(
        "/sessions/session-1/chat",
        json={"message": "Show monthly revenue trend"},
    ).json()
    assert job["status"] == "completed"
    assert job["final_state"]["chart_spec"]["artifact_ref"] is not None
    return client, job


def _chart_artifact_id(job: dict) -> str:
    """Extract artifact_id from a completed job response."""

    return job["final_state"]["chart_spec"]["artifact_ref"].rsplit(":", maxsplit=1)[-1]
