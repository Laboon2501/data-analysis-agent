"""Eval 指标计算测试。"""

from evals.metrics import EvalCase, evaluate_case_result
from schemas import AgentIntent, ChartSpec, ChartType, EventType
from schemas.agent_state import AgentState
from schemas.event import AgentEvent
from schemas.query_result import QueryColumn, QueryResult
from schemas.sql import SqlDialect, SqlDraft


def test_eval_metrics_pass_for_expected_direct_analysis_state() -> None:
    """符合期望的直接分析状态应通过全部适用指标。"""

    case = EvalCase(
        case_id="case-1",
        datasource_fixture="sqlite_orders",
        user_message="What is total revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
        expected_sql_contains=["SUM(revenue)", "FROM orders"],
        expected_tables=["orders"],
        expected_metrics=["orders.revenue"],
        expected_chart_type=ChartType.TABLE,
        must_not_contain=["DROP", "Thought:"],
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.DIRECT_ANALYSIS,
        sql_draft=SqlDraft(
            query="SELECT SUM(revenue) AS total_revenue FROM orders",
            dialect=SqlDialect.SQLITE,
        ),
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE),
        events=[
            AgentEvent(
                event_type=EventType.CHART_REF,
                payload={"artifact_ref": "artifact:chart-1"},
            )
        ],
    )

    result = evaluate_case_result(case, state)

    assert result.passed is True
    assert result.metrics["intent_accuracy"] is True
    assert result.metrics["sql_safety"] is True
    assert result.metrics["result_non_empty_rate"] is True
    assert result.violations == []


def test_eval_metrics_detect_large_event_payload() -> None:
    """事件 payload 中出现大内容时应触发大 payload 指标失败。"""

    case = EvalCase(
        case_id="case-2",
        datasource_fixture="sqlite_orders",
        user_message="What is total revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.DIRECT_ANALYSIS,
        events=[
            AgentEvent(
                event_type=EventType.ARTIFACT_REF,
                payload={"html": "<html>" + ("x" * 2_100)},
            )
        ],
    )

    result = evaluate_case_result(case, state)

    assert result.passed is False
    assert result.metrics["no_large_payload_in_events_history"] is False
    assert "no_large_payload_in_events_history" in result.violations


def test_eval_metrics_detect_react_marker() -> None:
    """事件或回复中出现 ReAct 痕迹时应失败。"""

    case = EvalCase(
        case_id="case-3",
        datasource_fixture="sqlite_orders",
        user_message="What is total revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.DIRECT_ANALYSIS,
        final_response_text="Thought: inspect every tool before answering.",
    )

    result = evaluate_case_result(case, state)

    assert result.passed is False
    assert result.metrics["no_react_tool_free_call_violation"] is False
