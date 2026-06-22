"""Tests for real report and Excel exports through the report graph."""

import json
from io import BytesIO

from openpyxl import load_workbook

from graphs.report_graph import build_report_graph
from persistence import InMemoryArtifactStore
from schemas import AgentCommand, AgentState, ChartSpec, ChartType, EventType, Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import EXCEL_MIME_TYPE, REPORT_MIME_TYPE


def test_report_graph_exports_markdown_report_fast_path() -> None:
    """report_confirm should reuse the saved outline and export Markdown."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    outline = _outline(ReportFormat.REPORT, package)

    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm report",
            command=AgentCommand.REPORT_CONFIRM,
            analysis_package=package,
            report_outline=outline,
        ),
        artifact_store,
    )

    assert state.report_outline.outline_id == outline.outline_id
    assert state.report_outline.title == outline.title
    assert state.report_result is not None
    assert state.report_result.status == "created"
    record = artifact_store.get_artifact(state.report_result.artifact_ref)
    assert record is not None
    assert record.metadata["mime_type"] == REPORT_MIME_TYPE
    assert record.metadata["source_analysis_package_id"] == package.package_id
    assert "# Saved report outline" in record.content


def test_report_graph_exports_excel_fast_path() -> None:
    """excel_confirm should reuse the saved outline and export XLSX bytes."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    outline = _outline(ReportFormat.EXCEL, package)

    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm excel",
            command=AgentCommand.EXCEL_CONFIRM,
            analysis_package=package,
            report_outline=outline,
        ),
        artifact_store,
    )

    assert state.report_outline.outline_id == outline.outline_id
    assert state.report_result is not None
    assert state.report_result.status == "created"
    record = artifact_store.get_artifact(state.report_result.artifact_ref)
    assert record is not None
    assert record.metadata["mime_type"] == EXCEL_MIME_TYPE
    workbook = load_workbook(BytesIO(record.content))
    assert workbook["Query Result"]["A2"].value == "2026-01"
    assert workbook["Query Result"]["B3"].value == 210


def test_report_graph_export_events_only_reference_artifact() -> None:
    """Export events should carry artifact refs and metadata, not file bodies."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm report",
            command=AgentCommand.REPORT_CONFIRM,
            analysis_package=package,
            report_outline=_outline(ReportFormat.REPORT, package),
        ),
        artifact_store,
    )

    artifact_events = [
        event for event in state.events if event.event_type is EventType.ARTIFACT_REF
    ]

    assert len(artifact_events) == 1
    assert artifact_events[0].payload["artifact_ref"] == state.report_result.artifact_ref
    serialized_events = json.dumps(
        [event.model_dump(mode="json") for event in state.events],
        sort_keys=True,
    )
    assert "# Saved report outline" not in serialized_events
    assert "| month | total_revenue |" not in serialized_events
    assert "2026-01" not in serialized_events


def _run_report_graph(state: AgentState, artifact_store: InMemoryArtifactStore) -> AgentState:
    """Run the report graph and validate the returned state."""

    return AgentState.model_validate(
        build_report_graph(artifact_store=artifact_store).invoke(state)
    )


def _analysis_package() -> AnalysisPackage:
    """Create an analysis package for real export graph tests."""

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


def _outline(report_format: ReportFormat, package: AnalysisPackage) -> ReportOutline:
    """Create a saved outline for confirm fast-path tests."""

    return ReportOutline(
        report_format=report_format,
        title=f"Saved {report_format.value} outline",
        sections=[ReportOutlineSection(title="Summary", points=["Use this exact outline."])],
        source_package_id=package.package_id,
    )
