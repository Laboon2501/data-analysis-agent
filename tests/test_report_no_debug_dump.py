"""Regression tests preventing debug identifiers in report bodies."""

from persistence import InMemoryArtifactStore
from schemas import Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import export_report


def test_report_body_omits_internal_ids_but_metadata_keeps_them() -> None:
    """正文不显示内部 ID；metadata 仍保留给开发者和系统使用。"""

    artifact_store = InMemoryArtifactStore()
    package = AnalysisPackage(
        question="Show summary",
        insights=[Insight(title="发现", summary="已生成一条摘要发现。")],
    )
    outline = ReportOutline(
        report_format=ReportFormat.REPORT,
        title="正常报告",
        sections=[ReportOutlineSection(title="摘要", points=["不要暴露内部 ID。"])],
        source_package_id=package.package_id,
    )

    result = export_report(outline, artifact_store, package)
    record = artifact_store.get_artifact(result.artifact_ref)

    assert record is not None
    assert record.metadata["outline_id"] == outline.outline_id
    assert record.metadata["source_analysis_package_id"] == package.package_id
    assert outline.outline_id not in record.content
    assert package.package_id not in record.content
    assert "Outline ID" not in record.content
    assert "Source package" not in record.content
