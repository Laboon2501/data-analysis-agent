"""Markdown report quality tests."""

from persistence import InMemoryArtifactStore
from schemas import Insight, ReportFormat
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportOutline, ReportOutlineSection
from tools.export_tools import export_report


def test_markdown_report_has_report_sections_without_debug_dump() -> None:
    """Markdown report should read like a report, not a serialized debug package."""

    artifact_store = InMemoryArtifactStore()
    package = AnalysisPackage(
        question="帮我看看这张表有什么可以分析的",
        sql_result=QueryResult(
            sql="SELECT SUM(column_12) AS total_column_12 FROM sheet",
            columns=[QueryColumn(name="total_column_12", data_type="real")],
            rows=[{"total_column_12": 123.0}],
            row_count=1,
        ),
        insights=[
            Insight(
                title="按经销商对比 pos",
                summary="A 经销商的 pos 表现最高，建议继续拆解其渠道来源。",
            ),
            Insight(
                title="按周观察 qtd",
                summary="第 2 周 qtd 达到阶段高点，后续可排查活动或补货影响。",
            ),
        ],
    )
    outline = ReportOutline(
        report_format=ReportFormat.REPORT,
        title="开放探索分析报告",
        sections=[ReportOutlineSection(title="摘要", points=["聚焦 pos 和 qtd 的变化。"])],
        source_package_id=package.package_id,
    )

    result = export_report(outline, artifact_store, package)
    record = artifact_store.get_artifact(result.artifact_ref)

    assert record is not None
    content = record.content
    headings = (
        "# 开放探索分析报告",
        "## 核心结论摘要",
        "## 主要发现",
        "## 数据限制",
        "## 后续建议",
    )
    for heading in headings:
        assert heading in content
    assert "A 经销商的 pos 表现最高" in content
    assert "total_column_12（未命名指标）" in content
    assert "Outline ID" not in content
    assert "Source package" not in content
    assert package.package_id not in content
    assert "Node name" not in content
    assert "retry attempt" not in content
