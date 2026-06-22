"""Rule fallback responses should be Chinese."""

from __future__ import annotations

from llm import FakeLLMClient
from nodes.insight_nodes import generate_insight
from nodes.planning_nodes import interpret_question
from schemas.agent_state import AgentState
from schemas.database_profile import ProfileStatus
from schemas.event import EventType
from schemas.query_result import QueryColumn, QueryResult
from tests.test_llm_strategy_nodes import _profile


def test_english_llm_insight_falls_back_to_chinese_rule_text() -> None:
    """English LLM natural language should not reach the user-facing final response."""

    state = AgentState(
        session_id="s",
        job_id="j",
        user_message="What is total revenue?",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )
    interpret_question(state)
    state.sql_result = QueryResult(
        sql="SELECT SUM(revenue) AS total_revenue FROM orders",
        columns=[QueryColumn(name="total_revenue", data_type="real")],
        rows=[{"total_revenue": 310.0}],
        row_count=1,
    )

    generate_insight(
        state,
        strategy="llm",
        llm_client=FakeLLMClient(
            ['{"title": "Revenue", "summary": "Revenue totals 310.", "evidence": []}']
        ),
    )

    assert state.insights[0].summary == "汇总结果为 310.0。"
    assert EventType.LLM_FALLBACK in {event.event_type for event in state.events}
