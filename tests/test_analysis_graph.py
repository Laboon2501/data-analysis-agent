"""Tests for the rule-based direct analysis graph."""

import pytest

from datasource import SQLAlchemyDataSource
from graphs.analysis_graph import build_analysis_graph
from nodes.execution_nodes import execute_sql
from nodes.result_check_nodes import check_result, repair_sql_if_needed
from nodes.sql_nodes import validate_sql
from persistence import InMemoryCacheStore
from schemas import AgentState, ChartType
from schemas.query_result import QueryColumn, QueryResult
from schemas.sql import SqlDialect, SqlDraft, SqlValidationStatus


def _run_analysis(sqlite_data_source: SQLAlchemyDataSource, question: str) -> AgentState:
    """Run the direct analysis graph and validate the returned state."""

    graph = build_analysis_graph(
        data_source=sqlite_data_source,
        cache_store=InMemoryCacheStore(),
    )
    result = graph.invoke(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message=question,
            datasource_id=sqlite_data_source.datasource_id,
        )
    )
    return AgentState.model_validate(result)


def test_analysis_graph_handles_simple_summary_question(sqlite_data_source) -> None:
    """A simple summary question should produce SQL, result, insight, and package."""

    state = _run_analysis(sqlite_data_source, "What is total revenue?")

    assert state.sql_draft is not None
    assert state.sql_draft.query == "SELECT SUM(revenue) AS total_revenue FROM orders"
    assert state.sql_validation is not None
    assert state.sql_validation.status is SqlValidationStatus.VALID
    assert state.sql_result is not None
    assert state.sql_result.rows == [{"total_revenue": 310.0}]
    assert state.chart_spec is not None
    assert state.chart_spec.chart_type is ChartType.TABLE
    assert state.analysis_package is not None
    assert state.analysis_package.sql_result == state.sql_result
    assert state.final_response_text == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"


def test_analysis_graph_handles_time_trend_question(sqlite_data_source) -> None:
    """A time trend question should group by the inferred time field."""

    state = _run_analysis(sqlite_data_source, "Show monthly revenue trend")

    assert state.sql_draft is not None
    assert state.sql_draft.query == (
        "SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month ORDER BY month"
    )
    assert state.sql_result is not None
    assert state.sql_result.rows == [
        {"month": "2026-01", "total_revenue": 100.0},
        {"month": "2026-02", "total_revenue": 210.0},
    ]
    assert state.chart_spec is not None
    assert state.chart_spec.chart_type is ChartType.LINE
    assert state.chart_spec.x == "month"
    assert state.chart_spec.y == "total_revenue"
    assert state.insights[0].summary == "已完成趋势分析，共返回 2 个时间点。"


def test_validate_sql_blocks_illegal_write_sql(sqlite_data_source) -> None:
    """Illegal write SQL should be rejected before execution."""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="bad sql",
        sql_draft=SqlDraft(query="DROP TABLE orders", dialect=SqlDialect.SQLITE),
    )

    validate_sql(state, data_source=sqlite_data_source)

    assert state.sql_validation is not None
    assert state.sql_validation.status is SqlValidationStatus.INVALID
    assert state.sql_validation.is_valid is False
    with pytest.raises(ValueError, match="valid before execution"):
        execute_sql(state, data_source=sqlite_data_source)


def test_check_result_marks_empty_results_for_repair_placeholder() -> None:
    """Empty results should be marked for bounded repair placeholder handling."""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="empty result",
        sql_result=QueryResult(
            sql="SELECT id FROM orders WHERE 1 = 0",
            columns=[QueryColumn(name="id", data_type="integer")],
            rows=[],
            row_count=0,
        ),
    )

    check_result(state)
    repair_sql_if_needed(state)

    assert state.result_check is not None
    assert state.result_check.is_empty is True
    assert state.result_check.needs_repair is True
    assert state.result_check.repair_attempts == 1


def test_analysis_package_contains_core_outputs(sqlite_data_source) -> None:
    """The direct graph should assemble an AnalysisPackage at the end."""

    state = _run_analysis(sqlite_data_source, "What is total revenue?")

    assert state.analysis_package is not None
    assert state.analysis_package.question == "What is total revenue?"
    assert state.analysis_package.analysis_plan == state.analysis_plan
    assert state.analysis_package.chart_spec == state.chart_spec
    assert state.analysis_package.insights == state.insights
