"""Tests for the rule-based report/export graph fast-path."""

import pytest

from graphs.report_graph import build_report_graph
from nodes.report_nodes import export_file
from persistence import InMemoryArtifactStore
from schemas import (
    AgentCommand,
    AgentState,
    ChartSpec,
    ChartType,
    HumanRequestType,
    Insight,
    ReportFormat,
    ReportOutline,
    ReportOutlineSection,
)
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult


def _analysis_package() -> AnalysisPackage:
    """Build a compact analysis package for export tests."""

    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(
            chart_type=ChartType.TABLE,
            title="Total revenue",
        ),
        insights=[
            Insight(
                title="Revenue summary",
                summary="\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002",
            )
        ],
    )


def _outline(report_format: ReportFormat) -> ReportOutline:
    """Build a saved outline that simulates a previous human preview step."""

    return ReportOutline(
        report_format=report_format,
        title=f"Saved {report_format.value} outline",
        sections=[
            ReportOutlineSection(
                title="Summary",
                points=["Keep this exact outline for the confirm fast-path."],
            )
        ],
        source_package_id="package-1",
    )


def _run_report_graph(state: AgentState, artifact_store: InMemoryArtifactStore) -> AgentState:
    """Invoke the report graph and validate the returned state model."""

    graph = build_report_graph(artifact_store=artifact_store)
    return AgentState.model_validate(graph.invoke(state))


def test_report_graph_generates_outline_from_analysis_package() -> None:
    """Outline stage should create a ReportOutline and stop for confirmation."""

    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        ),
        InMemoryArtifactStore(),
    )

    assert state.report_outline is not None
    assert state.report_outline.report_format is ReportFormat.REPORT
    assert state.report_outline.source_package_id == state.analysis_package.package_id
    assert state.report_result is None
    assert state.final_response_text is None


def test_report_graph_writes_human_confirmation_request() -> None:
    """Outline stage should emit a structured HumanRequest placeholder."""

    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        ),
        InMemoryArtifactStore(),
    )

    assert state.needs_human is True
    assert state.human_request is not None
    assert state.human_request.request_type is HumanRequestType.EXPORT_OUTLINE_CONFIRMATION
    assert state.human_request.context["outline_id"] == state.report_outline.outline_id


@pytest.mark.parametrize(
    ("command", "report_format", "expected_tool_name"),
    [
        (AgentCommand.REPORT_CONFIRM, ReportFormat.REPORT, "export_report"),
        (AgentCommand.PPT_CONFIRM, ReportFormat.PPT, "generate_ppt"),
    ],
)
def test_report_graph_runs_confirm_fast_path(
    command: AgentCommand,
    report_format: ReportFormat,
    expected_tool_name: str,
) -> None:
    """Confirm commands should export using the saved outline without analysis reruns."""

    artifact_store = InMemoryArtifactStore()
    saved_outline = _outline(report_format)
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirmed export",
            command=command,
            analysis_package=_analysis_package(),
            report_outline=saved_outline,
        ),
        artifact_store,
    )

    assert state.report_outline == saved_outline
    assert state.report_result is not None
    assert state.report_result.report_format is report_format
    assert state.report_result.artifact is not None
    assert state.report_result.artifact.artifact_ref == state.report_result.artifact_ref
    artifact_record = artifact_store.get_artifact(state.report_result.artifact_ref)
    assert artifact_record is not None
    assert artifact_record.metadata["tool_name"] == expected_tool_name
    if report_format is ReportFormat.REPORT:
        assert state.report_result.status == "created"
        assert artifact_record.metadata["placeholder"] is False
        assert artifact_record.metadata["report_type"] == "markdown_report"
    else:
        assert state.report_result.status == "created"
        assert artifact_record.metadata["placeholder"] is False
        assert artifact_record.metadata["report_type"] == "pptx"
    assert state.final_response_text is not None


def test_export_file_blocks_unconfirmed_command() -> None:
    """The export node should reject ordinary chat/report commands."""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="export immediately",
        command=AgentCommand.REPORT,
        report_outline=_outline(ReportFormat.REPORT),
    )

    with pytest.raises(PermissionError, match="not allowed to export"):
        export_file(state, artifact_store=InMemoryArtifactStore())


def test_confirm_fast_path_does_not_regenerate_outline() -> None:
    """Confirmed export must reuse the saved outline and keep its identity."""

    artifact_store = InMemoryArtifactStore()
    saved_outline = _outline(ReportFormat.REPORT)
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm report",
            command=AgentCommand.REPORT_CONFIRM,
            analysis_package=_analysis_package(),
            report_outline=saved_outline,
        ),
        artifact_store,
    )

    assert state.report_outline is not None
    assert state.report_outline.outline_id == saved_outline.outline_id
    assert state.report_outline.title == saved_outline.title


def test_confirm_without_saved_outline_generates_outline_before_export() -> None:
    """Confirm command with a prior AnalysisPackage should create an outline before export."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm report",
            command=AgentCommand.REPORT_CONFIRM,
            analysis_package=package,
        ),
        artifact_store,
    )

    assert state.report_outline is not None
    assert state.report_outline.report_format is ReportFormat.REPORT
    assert state.report_outline.source_package_id == package.package_id
    assert state.report_result is not None
    assert state.report_result.artifact_ref.startswith("artifact:")


def test_report_graph_generates_report_result_and_artifact_ref() -> None:
    """Confirmed exports should return ReportResult and structured ArtifactRef."""

    artifact_store = InMemoryArtifactStore()
    state = _run_report_graph(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="confirm dashboard",
            command=AgentCommand.DASHBOARD_CONFIRM,
            analysis_package=_analysis_package(),
            report_outline=_outline(ReportFormat.DASHBOARD),
        ),
        artifact_store,
    )

    assert state.report_result is not None
    assert state.report_result.artifact_ref.startswith("artifact:")
    assert state.report_result.artifact is not None
    assert state.report_result.artifact.artifact_type is ReportFormat.DASHBOARD
    assert state.report_result.status == "created"
    artifact_record = artifact_store.get_artifact(state.report_result.artifact_ref)
    assert artifact_record is not None
    assert artifact_record.metadata["report_type"] == "dashboard_spec"
    assert artifact_record.metadata["placeholder"] is False
