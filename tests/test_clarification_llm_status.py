"""Clarification/help replies should reflect effective LLM runtime status."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app.workers.job_runner as job_runner_module
from app.api import create_app
from app.config import AppConfig
from app.llm_runtime import LLMRuntimeMode, SessionLLMConfig
from app.workers import InMemoryJobRunner
from llm.fake import FakeLLMClient
from schemas.event import EventType


def test_real_llm_model_question_reports_provider_model_without_sql(
    monkeypatch,
    sqlite_data_source,
    tmp_path,
) -> None:
    """Model-status chat should use runtime status, not the fixed rule-mode template."""

    fake_client = FakeLLMClient(
        [
            (
                '{"answer":"当前已启用真实模型：deepseek/deepseek-chat。'
                '普通聊天不会执行 SQL，也不会调用工具。"}'
            )
        ]
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
            llm_api_key="test-api-key-secret",
            llm_config_path=str(tmp_path / "llm.json"),
        ),
    )
    runner.set_session_llm_config(
        "session-real",
        SessionLLMConfig(
            mode=LLMRuntimeMode.REAL_LLM,
            enabled_nodes=["planner", "sql_drafter", "insight_writer"],
        ),
    )
    client = TestClient(create_app(job_runner=runner, app_config=runner.app_config))

    response = client.post("/sessions/session-real/chat", json={"message": "你是什么模型？"})

    assert response.status_code == 200
    payload = response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "clarification"
    assert final_state["sql_draft"] is None
    assert "deepseek/deepseek-chat" in final_state["final_response_text"]
    assert "规则模式" not in final_state["final_response_text"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "test-api-key-secret" not in serialized
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert EventType.LLM_START.value in {event["event_type"] for event in events}
    assert EventType.TOOL_START.value not in {event["event_type"] for event in events}
    assert client.get("/sessions/session-real/llm").json()["last_llm_call_count"] == 1
    assert len(fake_client.calls) == 1


def test_rule_mode_model_question_reports_rule_mode(sqlite_data_source, tmp_path) -> None:
    """Only rule mode should say real model nodes are not enabled."""

    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        app_config=AppConfig(llm_config_path=str(tmp_path / "llm.json")),
    )
    client = TestClient(create_app(job_runner=runner, app_config=runner.app_config))

    response = client.post("/sessions/session-rule/chat", json={"message": "当前用的什么模型？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert "当前使用规则模式" in payload["final_state"]["final_response_text"]
    assert payload["final_state"]["sql_draft"] is None


def test_hi_help_reply_is_chinese_and_does_not_execute_sql(sqlite_data_source, tmp_path) -> None:
    """Help chat stays outside SQL while returning Chinese guidance."""

    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        app_config=AppConfig(llm_config_path=str(tmp_path / "llm.json")),
    )
    client = TestClient(create_app(job_runner=runner, app_config=runner.app_config))

    response = client.post("/sessions/session-help/chat", json={"message": "hi"})

    assert response.status_code == 200
    payload = response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "clarification"
    assert final_state["sql_result"] is None
    assert "你好，我是数据分析 Agent" in final_state["final_response_text"]
    assert "The summary value is" not in final_state["final_response_text"]
