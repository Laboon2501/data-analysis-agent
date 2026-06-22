"""Safety checks for no-tools ordinary chat in LLM mode."""

from fastapi.testclient import TestClient

import app.workers.job_runner as job_runner_module
from app.api import create_app
from app.config import AppConfig
from app.llm_runtime import LLMRuntimeMode, SessionLLMConfig
from app.workers import InMemoryJobRunner
from llm.fake import FakeLLMClient
from schemas.event import EventType


def test_real_llm_plain_chat_does_not_get_any_tools(
    monkeypatch,
    sqlite_data_source,
    tmp_path,
) -> None:
    """real_llm chat responder may call LLM, but it must not call SQL/tools/MCP."""

    fake_client = FakeLLMClient(
        ['{"answer":"我理解你的困惑。当前只是普通对话，不会执行 SQL，也不会调用任何工具。"}']
    )
    monkeypatch.setattr(
        job_runner_module,
        "build_llm_client_for_session",
        lambda _config, _app_config: fake_client,
    )
    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        app_config=AppConfig(
            llm_provider="deepseek",
            llm_model="deepseek-chat",
            llm_base_url="https://api.deepseek.com/v1",
            llm_api_key="test-chat-secret",
            llm_config_path=str(tmp_path / "llm.json"),
        ),
    )
    runner.set_session_llm_config(
        "chat-safe",
        SessionLLMConfig(mode=LLMRuntimeMode.REAL_LLM, enabled_nodes=["planner"]),
    )
    client = TestClient(create_app(job_runner=runner, app_config=runner.app_config))

    response = client.post("/sessions/chat-safe/chat", json={"message": "啊？"})

    assert response.status_code == 200
    payload = response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "clarification"
    assert final_state["sql_draft"] is None
    assert final_state["sql_result"] is None
    assert final_state["analysis_package"] is None
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    event_types = {event["event_type"] for event in events}
    event_blob = str(events)
    assert EventType.LLM_START.value in event_types
    assert EventType.TOOL_START.value not in event_types
    assert EventType.TOOL_END.value not in event_types
    assert "execute_sql" not in event_blob
    assert "query_data" not in event_blob
    assert "mcp__" not in event_blob
    assert "test-chat-secret" not in str(payload)
    assert "test-chat-secret" not in event_blob
    assert len(fake_client.calls) == 1
