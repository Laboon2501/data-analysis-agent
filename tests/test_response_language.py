"""Response language defaults for user-facing outputs."""

from __future__ import annotations

from app.config import AppConfig
from graphs.analysis_graph import build_analysis_graph
from graphs.open_exploration_graph import build_open_exploration_graph
from graphs.report_graph import build_report_graph
from persistence import InMemoryArtifactStore, InMemoryCacheStore
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.chart import ChartSpec, ChartType
from schemas.insight import Insight
from schemas.query_result import QueryColumn, QueryResult
from schemas.report import ReportFormat, ReportOutline, ReportOutlineSection


def test_app_config_defaults_response_language_to_zh_cn() -> None:
    """The release default should favor Chinese user-facing responses."""

    assert AppConfig().response_language == "zh-CN"
    assert AgentState(session_id="s", job_id="j", user_message="hi").response_language == "zh-CN"


def test_direct_analysis_final_response_is_chinese(sqlite_data_source) -> None:
    """Rule direct analysis should not return the old English template."""

    state = AgentState(
        session_id="s",
        job_id="j",
        user_message="Show monthly revenue trend",
        datasource_id=sqlite_data_source.datasource_id,
    )

    result = AgentState.model_validate(
        build_analysis_graph(
            data_source=sqlite_data_source,
            cache_store=InMemoryCacheStore(),
            artifact_store=InMemoryArtifactStore(),
        ).invoke(state)
    )

    assert result.final_response_text is not None
    assert "已完成趋势分析" in result.final_response_text
    assert "The time trend query returned" not in result.final_response_text


def test_open_exploration_final_response_is_chinese(sqlite_data_source) -> None:
    """Open exploration summary should be Chinese."""

    state = AgentState(
        session_id="s",
        job_id="j",
        user_message="Explore this datasource",
        command=AgentCommand.EXPLORE,
        intent=AgentIntent.OPEN_EXPLORATION,
        datasource_id=sqlite_data_source.datasource_id,
    )

    result = AgentState.model_validate(
        build_open_exploration_graph(
            data_source=sqlite_data_source,
            cache_store=InMemoryCacheStore(),
        ).invoke(state)
    )

    assert result.final_response_text is not None
    assert "已完成开放探索" in result.final_response_text
    assert "Open exploration completed" not in result.final_response_text


def test_report_confirm_final_response_is_chinese() -> None:
    """Export confirm fast-path should return a Chinese artifact message."""

    state = AgentState(
        session_id="s",
        job_id="j",
        user_message="excel_confirm",
        command=AgentCommand.EXCEL_CONFIRM,
        intent=AgentIntent.REPORT_EXPORT,
        analysis_package=_analysis_package(),
        report_outline=_outline(ReportFormat.EXCEL),
    )

    result = AgentState.model_validate(
        build_report_graph(artifact_store=InMemoryArtifactStore()).invoke(state)
    )

    assert result.final_response_text is not None
    assert "Excel 已生成：artifact:" in result.final_response_text
    assert "export is ready" not in result.final_response_text


def _analysis_package() -> AnalysisPackage:
    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE, title="Total revenue"),
        insights=[Insight(title="收入汇总", summary="汇总结果为 310.0。")],
    )


def _outline(report_format: ReportFormat) -> ReportOutline:
    return ReportOutline(
        report_format=report_format,
        title="导出大纲",
        sections=[ReportOutlineSection(title="摘要", points=["汇总结果"])],
        source_package_id="package-1",
    )
