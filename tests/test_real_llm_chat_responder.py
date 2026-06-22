"""No-tools real/fake LLM chat responder tests."""

from fastapi.testclient import TestClient

import app.workers.job_runner as job_runner_module
from app.api import create_app
from app.config import AppConfig
from app.llm_runtime import LLMRuntimeMode, SessionLLMConfig
from app.workers import InMemoryJobRunner
from llm.fake import FakeLLMClient
from schemas import EventType


def test_real_llm_chat_responder_uses_no_tools_and_reports_model(monkeypatch, tmp_path) -> None:
    """real_llm chat may call a no-tools responder but must not execute SQL/tools."""

    fake_client = FakeLLMClient(
        ['{"answer":"当前已配置真实模型：deepseek/deepseek-chat。普通聊天不会执行 SQL。"}']
    )
    monkeypatch.setattr(
        job_runner_module,
        "build_llm_client_for_session",
        lambda _config, _app_config: fake_client,
    )
    config = AppConfig(
        llm_provider="deepseek",
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.example/v1",
        llm_api_key="test-key-not-returned",
        llm_config_path=str(tmp_path / "llm.json"),
    )
    runner = InMemoryJobRunner(app_config=config)
    runner.set_session_llm_config(
        "real-chat",
        SessionLLMConfig(mode=LLMRuntimeMode.REAL_LLM, enabled_nodes=["planner"]),
    )
    client = TestClient(create_app(job_runner=runner, app_config=config))

    response = client.post("/sessions/real-chat/chat", json={"message": "你是什么模型？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_draft"] is None
    assert payload["final_state"]["sql_result"] is None
    assert "deepseek-chat" in payload["final_response_text"]
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    event_types = {event["event_type"] for event in events}
    assert EventType.LLM_START.value in event_types
    assert EventType.TOOL_START.value not in event_types
    assert "test-key-not-returned" not in str(payload)
    assert "test-key-not-returned" not in str(events)
    assert len(fake_client.calls) == 1
    assert client.get("/sessions/real-chat/llm").json()["last_llm_call_count"] == 1


def test_fake_llm_help_still_does_not_execute_sql(sqlite_data_source) -> None:
    """fake_llm chat responder is allowed, but SQL and tools remain disabled."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    runner.set_session_llm_config(
        "fake-chat",
        SessionLLMConfig(mode=LLMRuntimeMode.FAKE_LLM, enabled_nodes=["planner"]),
    )
    client = TestClient(create_app(job_runner=runner))

    response = client.post("/sessions/fake-chat/chat", json={"message": "hi"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_result"] is None
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert EventType.LLM_START.value in {event["event_type"] for event in events}
    assert EventType.TOOL_START.value not in {event["event_type"] for event in events}
