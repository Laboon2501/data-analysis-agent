"""Session-scoped LLM rollout integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.harness import build_initial_state
from app.llm_runtime import LLMRuntimeMode, SessionLLMConfig
from app.workers import InMemoryJobRunner
from schemas.event import EventType
from scripts.create_demo_db import create_demo_data_source


def test_default_rule_mode_does_not_call_llm(sqlite_data_source) -> None:
    """A normal analysis should stay rule-based unless the session enables LLM nodes."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner))

    response = client.post(
        "/sessions/session-rule/chat",
        json={"message": "Show monthly revenue trend"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert EventType.LLM_START.value not in {event["event_type"] for event in events}
    assert client.get("/sessions/session-rule/llm").json()["last_llm_call_count"] == 0


def test_fake_llm_session_emits_llm_events_for_enabled_nodes(sqlite_data_source) -> None:
    """fake_llm mode should exercise the existing LLM strategy and fallback events path."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    runner.set_session_llm_config(
        "session-fake",
        SessionLLMConfig(
            mode=LLMRuntimeMode.FAKE_LLM,
            enabled_nodes=["planner", "sql_drafter", "insight_writer"],
        ),
    )
    state = build_initial_state(
        session_id="session-fake",
        user_message="Show monthly revenue trend",
        datasource_id=sqlite_data_source.datasource_id,
    )

    job = runner.submit_job(state)

    assert job.status.value == "completed"
    assert job.final_state is not None
    assert job.final_state.insights[0].title == "\u89c4\u5219\u5206\u6790\u6d1e\u5bdf"
    event_types = {event.event_type for event in runner.list_events(job.job_id)}
    assert EventType.LLM_START in event_types
    assert EventType.LLM_END in event_types
    status = runner.get_session_llm_config("session-fake")
    assert status.mode is LLMRuntimeMode.FAKE_LLM
    assert status.last_llm_call_count >= 3
    assert status.last_llm_error_count == 0


def test_fake_llm_session_help_message_uses_no_tools_responder(sqlite_data_source) -> None:
    """Greeting/help messages may call no-tools LLM chat but never SQL/tools."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    runner.set_session_llm_config(
        "session-help",
        SessionLLMConfig(
            mode=LLMRuntimeMode.FAKE_LLM,
            enabled_nodes=["router", "planner", "sql_drafter", "insight_writer"],
        ),
    )
    client = TestClient(create_app(job_runner=runner))

    response = client.post("/sessions/session-help/chat", json={"message": "hi"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_result"] is None
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    event_types = {event["event_type"] for event in events}
    assert EventType.LLM_START.value in event_types
    assert EventType.TOOL_START.value not in event_types
    assert client.get("/sessions/session-help/llm").json()["last_llm_call_count"] == 1


def test_api_fake_llm_analysis_updates_status_counters(sqlite_data_source) -> None:
    """The API path should apply the saved session LLM config to later chat jobs."""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))
    set_response = client.post(
        "/sessions/session-api-fake/llm",
        json={
            "mode": "fake_llm",
            "enabled_nodes": ["planner", "sql_drafter", "insight_writer"],
        },
    )

    chat_response = client.post(
        "/sessions/session-api-fake/chat",
        json={"message": "Show monthly revenue trend"},
    )

    assert set_response.status_code == 200
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["status"] == "completed"
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert EventType.LLM_START.value in {event["event_type"] for event in events}
    status = client.get("/sessions/session-api-fake/llm").json()
    assert status["mode"] == "fake_llm"
    assert status["last_llm_call_count"] >= 3


def test_fake_llm_demo_trend_uses_metric_and_time_field_from_same_table() -> None:
    """Demo datasource fake LLM should not draft cross-table SQL without joins."""

    data_source = create_demo_data_source()
    runner = InMemoryJobRunner(data_source=data_source)
    runner.set_session_llm_config(
        "session-demo-fake",
        SessionLLMConfig(
            mode=LLMRuntimeMode.FAKE_LLM,
            enabled_nodes=["planner", "sql_drafter", "insight_writer"],
        ),
    )
    state = build_initial_state(
        session_id="session-demo-fake",
        user_message="近 12 个月销售趋势怎么样？",
        datasource_id=data_source.datasource_id,
    )

    job = runner.submit_job(state)

    assert job.status.value == "completed"
    assert job.error_message is None
    assert job.final_state is not None
    assert job.final_state.sql_draft is not None
    assert "FROM orders" in job.final_state.sql_draft.query
    assert "order_month" in job.final_state.sql_draft.query
