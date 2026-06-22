"""Tests for local LLM smoke script construction logic only."""

from app.harness import build_node_strategy_map
from llm import FakeLLMClient, LLMMessage
from nodes.insight_nodes import generate_insight
from schemas import AgentState, DirectQuestionKind, QueryResult
from schemas.direct_analysis import QuestionInterpretation
from schemas.query_result import QueryColumn
from scripts.run_llm_smoke import (
    DEFAULT_ENABLED_NODES,
    DebugLLMClient,
    SmokeDebugInfo,
    build_enabled_node_config,
    build_model_config,
    build_state_summary,
    create_demo_data_source,
    fallback_events_from_state,
    parse_args,
    requested_llm_nodes,
)


def test_smoke_script_parse_args_defaults() -> None:
    """Default args should not enable network execution by themselves."""

    args = parse_args(["--model", "gpt-test"])

    assert args.provider == "openai_compatible"
    assert args.model == "gpt-test"
    assert args.base_url == "https://api.openai.com/v1"
    assert args.api_key_env == "OPENAI_API_KEY"
    assert args.timeout_seconds == 30
    assert args.max_retries == 1
    assert args.temperature == 0
    assert args.max_tokens is None
    assert args.enabled_nodes is None
    assert args.question == "Show monthly revenue trend"
    assert requested_llm_nodes(args) == list(DEFAULT_ENABLED_NODES)


def test_smoke_script_builds_model_config_from_args() -> None:
    """CLI args should map into ModelConfig without reading environment variables."""

    args = parse_args(
        [
            "--model",
            "custom-model",
            "--base-url",
            "https://gateway.example/v1",
            "--api-key-env",
            "CUSTOM_LLM_KEY",
            "--timeout-seconds",
            "9",
            "--max-retries",
            "2",
            "--temperature",
            "0.3",
            "--max-tokens",
            "500",
        ]
    )

    config = build_model_config(args)

    assert config.model == "custom-model"
    assert config.base_url == "https://gateway.example/v1"
    assert config.api_key_env == "CUSTOM_LLM_KEY"
    assert config.timeout_seconds == 9
    assert config.max_retries == 2
    assert config.temperature == 0.3
    assert config.max_tokens == 500


def test_smoke_script_builds_default_enabled_node_config() -> None:
    """Smoke script should default to a small set of LLM nodes."""

    args = parse_args(["--model", "gpt-test"])
    config = build_enabled_node_config(args)

    assert config.enabled_nodes == list(DEFAULT_ENABLED_NODES)
    assert build_node_strategy_map(config) == {
        "draft_sql": "llm",
        "generate_insight": "llm",
    }


def test_smoke_script_accepts_repeated_llm_node_flags() -> None:
    """Repeated --llm-node flags should feed the rollout map."""

    args = parse_args(
        [
            "--model",
            "gpt-test",
            "--llm-node",
            "router",
            "--llm-node",
            "planner",
        ]
    )
    config = build_enabled_node_config(args)

    assert config.enabled_nodes == ["router", "planner"]
    assert build_node_strategy_map(config) == {
        "route": "llm",
        "interpret_question": "llm",
        "make_analysis_plan": "llm",
    }


def test_smoke_script_aliases_all_supported_llm_nodes() -> None:
    """CLI aliases should map to the actual graph node names."""

    args = parse_args(
        [
            "--model",
            "gpt-test",
            "--llm-node",
            "router",
            "--llm-node",
            "planner",
            "--llm-node",
            "sql_drafter",
            "--llm-node",
            "insight_writer",
        ]
    )
    config = build_enabled_node_config(args)

    assert requested_llm_nodes(args) == [
        "router",
        "planner",
        "sql_drafter",
        "insight_writer",
    ]
    assert build_node_strategy_map(config) == {
        "route": "llm",
        "interpret_question": "llm",
        "make_analysis_plan": "llm",
        "draft_sql": "llm",
        "generate_insight": "llm",
    }


def test_smoke_script_creates_demo_sqlite_datasource() -> None:
    """The demo datasource should be usable without network access."""

    data_source = create_demo_data_source()

    assert data_source.datasource_id == "llm-smoke-sqlite"
    assert data_source.list_tables() == ["orders"]
    result = data_source.query(
        "SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month ORDER BY month"
    )
    assert result.row_count == 3
    assert result.rows[0] == {"month": "2026-01", "total_revenue": 100.0}


def test_debug_llm_client_records_system_prompt_first_line() -> None:
    """Debug wrapper should record prompt first lines without changing responses."""

    client = DebugLLMClient(FakeLLMClient(['{"summary": "ok"}']))

    response = client.complete(
        [
            LLMMessage(role="system", content="# Insight Writer\n\nWrite one insight."),
            LLMMessage(role="user", content="{}"),
        ]
    )

    assert response.content == '{"summary": "ok"}'
    assert client.call_count == 1
    assert client.call_prompts == ["# Insight Writer"]


def test_smoke_summary_includes_fallback_event_for_invalid_insight_json() -> None:
    """Invalid LLM JSON should be visible in smoke fallback events."""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is total revenue?",
        question_interpretation=QuestionInterpretation(
            question="What is total revenue?",
            kind=DirectQuestionKind.SUMMARY,
            table_name="orders",
            metric_field="orders.revenue",
        ),
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
    )
    generate_insight(state, strategy="llm", llm_client=FakeLLMClient(["not-json"]))
    debug = SmokeDebugInfo(
        requested_llm_nodes=["insight_writer"],
        enabled_llm_nodes={"generate_insight": "llm"},
        llm_call_prompts=["# Insight Writer"],
    )

    fallback_events = fallback_events_from_state(state)
    summary = build_state_summary(state, debug)

    assert state.insights[0].title == "\u89c4\u5219\u5206\u6790\u6d1e\u5bdf"
    assert fallback_events[0]["node"] == "generate_insight"
    assert fallback_events[0]["error_code"] == "json_invalid"
    assert fallback_events[0]["error_type"] == "LLMAdapterError"
    assert summary["requested_llm_nodes"] == ["insight_writer"]
    assert summary["enabled_llm_nodes"] == {"generate_insight": "llm"}
    assert summary["llm_call_count"] == 1
    assert summary["llm_call_prompts"] == ["# Insight Writer"]
    assert summary["fallback_events"][0]["node"] == "generate_insight"
