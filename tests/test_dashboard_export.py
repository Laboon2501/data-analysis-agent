"""Tests for dashboard spec artifact export."""

from persistence import InMemoryArtifactStore
from schemas import ChartSpec, ChartType, Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import (
    DASHBOARD_MIME_TYPE,
    generate_dashboard,
    propose_dashboard_outline,
)


def test_propose_dashboard_outline_describes_widgets_and_filters() -> None:
    """Dashboard outline should describe the dashboard plan from AnalysisPackage."""

    outline = propose_dashboard_outline(_analysis_package())

    assert outline.report_format is ReportFormat.DASHBOARD
    assert outline.title.startswith("Analysis dashboard:")
    assert [section.title for section in outline.sections] == [
        "Overview",
        "Widgets",
        "Filters",
    ]
    assert any("Chart widget references artifact" in point for point in outline.sections[1].points)
    assert "Filter candidate: month" in outline.sections[2].points


def test_generate_dashboard_creates_json_spec_artifact() -> None:
    """Dashboard export should persist a structured JSON spec artifact."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    outline = _outline(package)

    result = generate_dashboard(outline, artifact_store, package)

    assert result.report_format is ReportFormat.DASHBOARD
    assert result.status == "created"
    record = artifact_store.get_artifact(result.artifact_ref)
    assert record is not None
    assert record.metadata["mime_type"] == DASHBOARD_MIME_TYPE
    assert record.metadata["report_type"] == "dashboard_spec"
    assert record.metadata["source_analysis_package_id"] == package.package_id
    assert record.metadata["placeholder"] is False
    assert record.metadata["widget_count"] == 4
    assert record.metadata["chart_artifact_refs"] == ["artifact:chart-1"]

    content = record.content
    assert content["title"] == "Revenue dashboard"
    assert content["source_package_id"] == package.package_id
    assert content["question"] == "Show monthly revenue trend"
    assert {widget["widget_type"] for widget in content["widgets"]} == {
        "metric",
        "chart",
        "table",
        "insight",
    }
    chart_widget = next(widget for widget in content["widgets"] if widget["widget_type"] == "chart")
    table_widget = next(widget for widget in content["widgets"] if widget["widget_type"] == "table")
    assert chart_widget["chart_artifact_ref"] == "artifact:chart-1"
    assert chart_widget["chart_type"] == "line"
    assert table_widget["metadata"]["columns"] == ["month", "total_revenue"]
    assert "rows" not in table_widget["metadata"]
    assert "rows" not in content


def test_generate_dashboard_without_package_uses_saved_outline_only() -> None:
    """Confirm fast-path can create a dashboard spec from a saved outline alone."""

    artifact_store = InMemoryArtifactStore()
    outline = ReportOutline(
        report_format=ReportFormat.DASHBOARD,
        title="Saved dashboard outline",
        sections=[ReportOutlineSection(title="Summary", points=["Use saved dashboard."])],
        source_package_id="package-1",
    )

    result = generate_dashboard(outline, artifact_store)
    record = artifact_store.get_artifact(result.artifact_ref)

    assert result.status == "created"
    assert record is not None
    assert record.metadata["source_analysis_package_id"] == "package-1"
    assert record.content["widgets"][0]["widget_type"] == "text"
    assert record.content["widgets"][0]["metadata"]["sections"][0]["points"] == [
        "Use saved dashboard."
    ]


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
    """Create a dashboard outline tied to a package."""

    return ReportOutline(
        report_format=ReportFormat.DASHBOARD,
        title="Revenue dashboard",
        sections=[ReportOutlineSection(title="Widgets", points=["Use metric and chart."])],
        source_package_id=package.package_id,
    )
