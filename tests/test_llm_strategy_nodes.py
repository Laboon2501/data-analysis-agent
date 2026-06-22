"""Tests for nodes that support optional LLM strategy switching."""

from app.harness import LLMNodeStrategyConfig, build_initial_state, build_node_strategy_map
from graphs.analysis_graph import build_analysis_graph
from llm import FakeLLMClient
from nodes.insight_nodes import generate_insight
from nodes.planning_nodes import interpret_question, make_analysis_plan
from nodes.router import route
from nodes.sql_nodes import draft_sql, validate_sql
from schemas import (
    AgentCommand,
    AgentIntent,
    AgentState,
    DirectQuestionKind,
    FieldProfile,
    FieldSemanticType,
    ProfileStatus,
    QueryResult,
    TableProfile,
)
from schemas.database_profile import DatabaseProfile
from schemas.query_result import QueryColumn


def _profile() -> DatabaseProfile:
    """Build a compact profile with one metric and one time field."""

    return DatabaseProfile(
        datasource_id="test-sqlite",
        schema_hash="hash-1",
        status=ProfileStatus.CONFIRMED,
        tables=[
            TableProfile(
                name="orders",
                row_count=3,
                columns=[
                    FieldProfile(
                        name="month",
                        data_type="TEXT",
                        semantic_type=FieldSemanticType.DATETIME,
                    ),
                    FieldProfile(
                        name="revenue",
                        data_type="REAL",
                        semantic_type=FieldSemanticType.CURRENCY,
                        is_metric_candidate=True,
                    ),
                ],
            )
        ],
        time_fields=["orders.month"],
        metric_fields=["orders.revenue"],
        candidate_metrics=["orders.revenue"],
        candidate_dimensions=["orders.month"],
    )


def test_router_supports_llm_strategy_with_fake_client() -> None:
    """Router should accept structured fake LLM output when strategy is llm."""

    client = FakeLLMClient(
        ['{"command": "explore", "intent": "open_exploration", "reason": "broad ask"}']
    )
    state = AgentState(session_id="session-1", job_id="job-1", user_message="Explore data")

    route(state, strategy="llm", llm_client=client)

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert len(client.calls) == 1
    assert "# Router" in client.calls[0][0].content


def test_planning_sql_and_insight_nodes_support_llm_strategy(sqlite_data_source) -> None:
    """Selected nodes should map fake LLM JSON into structured workflow schemas."""

    client = FakeLLMClient(
        [
            (
                '{"question": "Show monthly revenue trend", "kind": "time_trend", '
                '"table_name": "orders", "metric_field": "orders.revenue", '
                '"time_field": "orders.month", "dimension_field": null, "top_n": null}'
            ),
            (
                '{"steps": [{"name": "draft_sql", "objective": "Draft read-only SQL.", '
                '"required_inputs": ["database_profile"], "expected_outputs": ["sql_draft"], '
                '"tool_categories": ["sql"]}], "assumptions": ["Use revenue."], "risks": []}'
            ),
            (
                '{"query": "SELECT month, SUM(revenue) AS total_revenue FROM orders '
                'GROUP BY month ORDER BY month", "rationale": "Monthly revenue trend."}'
            ),
            (
                '{"title": "Monthly revenue", '
                '"summary": "已完成趋势分析，共返回 2 个时间点。", '
                '"evidence": ["row_count=2"], "confidence": 0.8}'
            ),
        ]
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="Show monthly revenue trend",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )

    interpret_question(state, strategy="llm", llm_client=client)
    make_analysis_plan(state, strategy="llm", llm_client=client)
    draft_sql(state, data_source=sqlite_data_source, strategy="llm", llm_client=client)
    state.sql_result = QueryResult(
        sql=state.sql_draft.query,
        columns=[
            QueryColumn(name="month", data_type="text"),
            QueryColumn(name="total_revenue", data_type="real"),
        ],
        rows=[
            {"month": "2026-01", "total_revenue": 100.0},
            {"month": "2026-02", "total_revenue": 210.0},
        ],
        row_count=2,
    )
    generate_insight(state, strategy="llm", llm_client=client)

    assert state.question_interpretation is not None
    assert state.question_interpretation.kind is DirectQuestionKind.TIME_TREND
    assert state.analysis_plan is not None
    assert state.analysis_plan.steps[0].name == "draft_sql"
    assert state.sql_draft is not None
    assert state.sql_draft.referenced_tables == ["orders"]
    assert state.insights[0].summary == "已完成趋势分析，共返回 2 个时间点。"
    assert len(client.calls) == 4


def test_default_strategy_keeps_rule_path_and_does_not_call_llm(sqlite_data_source) -> None:
    """Passing a fake client without llm strategy should not change rule behavior."""

    client = FakeLLMClient()
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is total revenue?",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )

    interpret_question(state, llm_client=client)
    make_analysis_plan(state, llm_client=client)
    draft_sql(state, data_source=sqlite_data_source, llm_client=client)
    state.sql_result = QueryResult(
        sql=state.sql_draft.query,
        columns=[QueryColumn(name="total_revenue", data_type="real")],
        rows=[{"total_revenue": 310.0}],
        row_count=1,
    )
    generate_insight(state, llm_client=client)

    assert state.question_interpretation.kind is DirectQuestionKind.SUMMARY
    assert state.sql_draft.query == "SELECT SUM(revenue) AS total_revenue FROM orders"
    assert state.insights[0].summary == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"
    assert client.calls == []


def test_harness_can_use_optional_llm_router_injection() -> None:
    """App harness should allow explicit LLM routing while defaulting to rules."""

    client = FakeLLMClient(['{"command": "report", "intent": "report_export"}'])

    state = build_initial_state(
        session_id="session-1",
        user_message="Make something for leadership",
        llm_client=client,
        route_strategy="llm",
    )

    assert state.command is AgentCommand.REPORT
    assert state.intent is AgentIntent.REPORT_EXPORT
    assert len(client.calls) == 1


def test_harness_strategy_config_enables_llm_router() -> None:
    """A rollout config should enable only the configured router node."""

    client = FakeLLMClient(['{"command": "explore", "intent": "open_exploration"}'])

    state = build_initial_state(
        session_id="session-1",
        user_message="Investigate this dataset",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert len(client.calls) == 1


def test_analysis_graph_can_enable_only_llm_sql_drafter(sqlite_data_source) -> None:
    """Per-node rollout should allow LLM SQL drafting without enabling every node."""

    client = FakeLLMClient(
        [
            (
                '{"query": "SELECT SUM(revenue) AS total_revenue FROM orders", '
                '"rationale": "LLM summary query."}'
            )
        ]
    )
    graph = build_analysis_graph(
        data_source=sqlite_data_source,
        node_strategies=build_node_strategy_map(
            LLMNodeStrategyConfig(enabled_nodes=["sql_drafter"])
        ),
        llm_client=client,
    )

    result = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="What is total revenue?",
                datasource_id=sqlite_data_source.datasource_id,
            )
        )
    )

    assert result.sql_draft is not None
    assert result.sql_draft.rationale == "LLM summary query."
    assert result.sql_result is not None
    assert result.sql_result.rows == [{"total_revenue": 310.0}]
    assert result.final_response_text == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"
    assert len(client.calls) == 1


def test_invalid_llm_json_falls_back_to_rule_sql_drafter(sqlite_data_source) -> None:
    """Invalid JSON from the LLM should fall back to deterministic SQL drafting."""

    client = FakeLLMClient(["not json"])
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is total revenue?",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )
    interpret_question(state)

    draft_sql(state, data_source=sqlite_data_source, strategy="llm", llm_client=client)

    assert state.sql_draft is not None
    assert state.sql_draft.query == "SELECT SUM(revenue) AS total_revenue FROM orders"
    assert state.sql_draft.rationale == "Rule-based SQL for summary."
    assert len(client.calls) == 1


def test_llm_error_falls_back_to_rule_insight() -> None:
    """LLM adapter errors should fall back to deterministic insight writing."""

    client = FakeLLMClient()
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
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

    generate_insight(state, strategy="llm", llm_client=client)

    assert state.insights[0].summary == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"
    assert len(client.calls) == 1


def test_llm_sql_drafter_result_still_goes_through_sql_guard(sqlite_data_source) -> None:
    """Dangerous LLM SQL should stay in draft state and be rejected by validate_sql."""

    client = FakeLLMClient(['{"query": "DROP TABLE orders", "rationale": "bad sql"}'])
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is total revenue?",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )
    interpret_question(state)

    draft_sql(state, data_source=sqlite_data_source, strategy="llm", llm_client=client)
    validate_sql(state, data_source=sqlite_data_source)

    assert state.sql_draft is not None
    assert state.sql_draft.query == "DROP TABLE orders"
    assert state.sql_validation is not None
    assert state.sql_validation.is_valid is False
    assert "Only SELECT or WITH SELECT statements are allowed." in state.sql_validation.errors
    assert len(client.calls) == 1
