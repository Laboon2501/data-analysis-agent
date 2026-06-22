"""Tests for lightweight report export artifacts."""

from persistence import InMemoryArtifactStore
from schemas import ChartSpec, ChartType, Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import REPORT_MIME_TYPE, export_report


def test_export_report_creates_markdown_artifact() -> None:
    """Report export should persist Markdown content and metadata."""

    artifact_store = InMemoryArtifactStore()
    package = _analysis_package()
    outline = _outline(package)

    result = export_report(outline, artifact_store, package)

    assert result.report_format is ReportFormat.REPORT
    assert result.status == "created"
    record = artifact_store.get_artifact(result.artifact_ref)
    assert record is not None
    assert record.metadata["mime_type"] == REPORT_MIME_TYPE
    assert record.metadata["report_type"] == "markdown_report"
    assert record.metadata["source_analysis_package_id"] == package.package_id
    assert record.metadata["placeholder"] is False
    assert "# Revenue report" in record.content
    assert "Show monthly revenue trend" in record.content
    assert "Revenue increased across the period." in record.content
    assert "| month | total_revenue |" in record.content
    assert "图表建议" in record.content
    assert "artifact:chart-1" not in record.content
    assert "Outline ID" not in record.content
    assert "Source package" not in record.content


def test_export_report_can_use_outline_without_reanalyzing_data() -> None:
    """Confirm fast-paths with only a saved outline should still create a report."""

    artifact_store = InMemoryArtifactStore()
    outline = ReportOutline(
        report_format=ReportFormat.REPORT,
        title="Saved report outline",
        sections=[ReportOutlineSection(title="Summary", points=["Use saved outline."])],
        source_package_id="package-1",
    )

    result = export_report(outline, artifact_store)
    record = artifact_store.get_artifact(result.artifact_ref)

    assert result.status == "created"
    assert record is not None
    assert record.metadata["source_analysis_package_id"] == "package-1"
    assert "Use saved outline." in record.content


def _analysis_package() -> AnalysisPackage:
    """Create an analysis package for report export."""

    return AnalysisPackage(
        question="Show monthly revenue trend",
        sql_result=QueryResult(
            sql="SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month",
            columns=[
                QueryColumn(name="month", data_type="text"),
                QueryColumn(name="total_revenue", data_type="real"),
            ],
            rows=[{"month": "2026-01", "total_revenue": 100.0}],
            row_count=1,
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
    """Create a report outline tied to a package."""

    return ReportOutline(
        report_format=ReportFormat.REPORT,
        title="Revenue report",
        sections=[ReportOutlineSection(title="Summary", points=["Include the key trend."])],
        source_package_id=package.package_id,
    )
