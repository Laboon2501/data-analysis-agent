"""Stronger LLM eval summary metric tests."""

from __future__ import annotations

from evals.metrics import EvalCase, evaluate_case_result, summarize_eval_results
from schemas import AgentIntent, EventType
from schemas.agent_state import AgentState
from schemas.event import AgentEvent
from schemas.sql import SqlDialect, SqlDraft


def test_eval_summary_exposes_llm_specific_rates() -> None:
    """Summary stats should include fallback/json-invalid and named pass rates."""

    case = EvalCase(
        case_id="summary-metrics",
        tags=["sql"],
        datasource_fixture="sqlite_orders",
        user_message="What is revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
        expected_tables=["orders"],
        expected_metrics=["orders.revenue"],
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
        events=[
            AgentEvent(event_type=EventType.LLM_START, node_name="draft_sql"),
            AgentEvent(event_type=EventType.LLM_JSON_INVALID, node_name="draft_sql"),
            AgentEvent(event_type=EventType.LLM_FALLBACK, node_name="draft_sql"),
        ],
    )

    summary = summarize_eval_results([evaluate_case_result(case, state)])

    assert summary.stats["intent_accuracy"] == 1.0
    assert summary.stats["sql_table_match_rate"] == 1.0
    assert summary.stats["sql_field_match_rate"] == 1.0
    assert summary.stats["fallback_rate"] == 1.0
    assert summary.stats["json_invalid_rate"] == 1.0
    assert summary.stats["artifact_pass_rate"] is None


def test_no_sql_for_chat_pass_rate_is_summarized() -> None:
    """Clarification/chat cases should expose a no-SQL pass rate."""

    case = EvalCase(
        case_id="chat-help",
        tags=["chat", "no-sql"],
        datasource_fixture="sqlite_orders",
        user_message="hi",
        expected_intent=AgentIntent.CLARIFICATION,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.CLARIFICATION,
    )

    summary = summarize_eval_results([evaluate_case_result(case, state)])

    assert summary.metric_rates["no_sql_for_chat"] == 1.0
    assert summary.stats["no_sql_for_chat_pass_rate"] == 1.0
