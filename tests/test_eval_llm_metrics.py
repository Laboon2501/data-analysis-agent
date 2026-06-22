"""Tests for LLM-related eval diagnostic stats."""

from __future__ import annotations

from evals.metrics import EvalCase, evaluate_case_result, summarize_eval_results
from schemas import AgentIntent, EventType
from schemas.agent_state import AgentState
from schemas.event import AgentEvent
from schemas.sql import SqlDialect, SqlDraft


def test_eval_stats_count_llm_events_and_sql_guard_blocks() -> None:
    """LLM observability and SQLGuard diagnostics should be counted per case."""

    case = EvalCase(
        case_id="llm-stats",
        datasource_fixture="sqlite_orders",
        user_message="What is revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.DIRECT_ANALYSIS,
        sql_draft=SqlDraft(query="DROP TABLE orders", dialect=SqlDialect.SQLITE),
        events=[
            AgentEvent(event_type=EventType.LLM_START, node_name="draft_sql"),
            AgentEvent(event_type=EventType.LLM_ERROR, node_name="draft_sql"),
            AgentEvent(event_type=EventType.LLM_JSON_INVALID, node_name="draft_sql"),
            AgentEvent(event_type=EventType.LLM_FALLBACK, node_name="draft_sql"),
        ],
    )

    result = evaluate_case_result(case, state)

    assert result.stats["llm_call_count"] == 1
    assert result.stats["llm_error_count"] == 1
    assert result.stats["llm_json_invalid_count"] == 1
    assert result.stats["llm_fallback_count"] == 1
    assert result.stats["sql_guard_block_count"] == 1
    assert result.stats["generated_sql_valid_rate"] == 0.0
    assert result.metrics["sql_safety"] is False


def test_eval_summary_aggregates_llm_stats() -> None:
    """EvalSummary should aggregate count stats and generated SQL validity."""

    passing = _result_with_sql("SELECT SUM(revenue) FROM orders")
    blocked = _result_with_sql("DROP TABLE orders")

    summary = summarize_eval_results([passing, blocked])

    assert summary.stats["llm_call_count"] == 2
    assert summary.stats["sql_guard_block_count"] == 1
    assert summary.stats["generated_sql_count"] == 2
    assert summary.stats["generated_sql_valid_count"] == 1
    assert summary.stats["generated_sql_valid_rate"] == 0.5


def _result_with_sql(sql: str):
    """Build one eval result with a single LLM call and SQL string."""

    case = EvalCase(
        case_id=f"case-{sql[:4]}",
        datasource_fixture="sqlite_orders",
        user_message="What is revenue?",
        expected_intent=AgentIntent.DIRECT_ANALYSIS,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=case.user_message,
        intent=AgentIntent.DIRECT_ANALYSIS,
        sql_draft=SqlDraft(query=sql, dialect=SqlDialect.SQLITE),
        events=[AgentEvent(event_type=EventType.LLM_START, node_name="draft_sql")],
    )
    return evaluate_case_result(case, state)
