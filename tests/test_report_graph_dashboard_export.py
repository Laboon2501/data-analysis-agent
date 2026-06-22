"""Tests for dashboard spec export through report graph and artifact API."""

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from graphs.report_graph import build_report_graph
from persistence import InMemoryArtifactStore
from schemas import AgentCommand, AgentState, ChartSpec, ChartType, EventType, Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import DASHBOARD_MIME_TYPE


def test_report_graph_exports_dashboard_spec_fast_path_without_replanning() -> None:
    """dashboard_confirm should reuse the saved outline and create dashboard JSON."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    outline = _outline(package)

    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm dashboard",
            command=AgentCommand.DASHBOARD_CONFIRM,
            analysis_package=package,
            report_outline=outline,
        ),
        artifact_store,
    )

    assert state.report_outline.outline_id == outline.outline_id
    assert state.report_outline.title == outline.title
    assert state.report_result is not None
    assert state.report_result.status == "created"
    assert state.report_result.report_format is ReportFormat.DASHBOARD

    record = artifact_store.get_artifact(state.report_result.artifact_ref)
    assert record is not None
    assert record.metadata["mime_type"] == DASHBOARD_MIME_TYPE
    assert record.metadata["report_type"] == "dashboard_spec"
    assert record.metadata["placeholder"] is False
    assert record.metadata["source_analysis_package_id"] == package.package_id
    assert record.content["title"] == "Saved dashboard outline"
    chart_widget = next(
        widget for widget in record.content["widgets"] if widget["widget_type"] == "chart"
    )
    assert chart_widget["chart_artifact_ref"] == "artifact:chart-1"
    assert "rows" not in record.content


def test_dashboard_artifact_is_readable_through_artifact_api() -> None:
    """Existing artifact API should return dashboard metadata and JSON content."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm dashboard",
            command=AgentCommand.DASHBOARD_CONFIRM,
            analysis_package=package,
            report_outline=_outline(package),
        ),
        artifact_store,
    )
    artifact_id = state.report_result.artifact_ref.rsplit(":", maxsplit=1)[-1]
    client = TestClient(create_app(job_runner=InMemoryJobRunner(artifact_store=artifact_store)))

    metadata_response = client.get(f"/artifacts/{artifact_id}")
    content_response = client.get(f"/artifacts/{artifact_id}/content")

    assert metadata_response.status_code == 200
    assert metadata_response.json()["mime_type"] == DASHBOARD_MIME_TYPE
    assert "content" not in metadata_response.json()
    assert content_response.status_code == 200
    assert content_response.headers["content-type"].startswith(DASHBOARD_MIME_TYPE)
    chart_widget = next(
        widget for widget in content_response.json()["widgets"] if widget["widget_type"] == "chart"
    )
    assert chart_widget["chart_artifact_ref"] == "artifact:chart-1"


def test_dashboard_export_events_only_reference_artifact() -> None:
    """Dashboard events should not include the full dashboard spec JSON body."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm dashboard",
            command=AgentCommand.DASHBOARD_CONFIRM,
            analysis_package=package,
            report_outline=_outline(package),
        ),
        artifact_store,
    )

    artifact_events = [
        event for event in state.events if event.event_type is EventType.ARTIFACT_REF
    ]
    serialized_events = json.dumps(
        [event.model_dump(mode="json") for event in state.events],
        sort_keys=True,
    )

    assert len(artifact_events) == 1
    assert artifact_events[0].payload["artifact_ref"] == state.report_result.artifact_ref
    assert '"widgets"' not in serialized_events
    assert '"filters"' not in serialized_events
    assert "2026-01" not in serialized_events
    assert "Revenue increased across the period." not in serialized_events


def _run_report_graph(state: AgentState, artifact_store: InMemoryArtifactStore) -> AgentState:
    """Run report graph and validate returned state."""

    return AgentState.model_validate(
        build_report_graph(artifact_store=artifact_store).invoke(state)
    )


def _analysis_package() -> AnalysisPackage:
    """Create an analysis package with chart artifact reference."""

    return AnalysisPackage(
        question="Show monthly revenue trend",
        sql_result=QueryResult(
            sql="SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month",
            columns=[
                QueryColumn(name="month", data_type="text"),
                QueryColumn(name="total_revenue", data_type="real"),
            ],
            rows=[
                {"month": "2026-01", "total_revenue": 100.0},
                {"month": "2026-02", "total_revenue": 210.0},
            ],
            row_count=2,
        ),
        chart_spec=ChartSpec(
            chart_type=ChartType.LINE,
            title="Monthly revenue",
            artifact_ref="artifact:chart-1",
        ),
        insights=[
            Insight(
                title="Revenue trend",
                summary="Revenue increased across the period.",
            )
        ],
    )


def _outline(package: AnalysisPackage) -> ReportOutline:
    """Create a saved dashboard outline."""

    return ReportOutline(
        report_format=ReportFormat.DASHBOARD,
        title="Saved dashboard outline",
        sections=[ReportOutlineSection(title="Widgets", points=["Use saved dashboard."])],
        source_package_id=package.package_id,
    )
