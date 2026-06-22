"""Session title generation tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.sessions import SessionTitleSource
from app.workers import InMemoryJobRunner


def test_rule_title_uses_first_user_message(tmp_path, sqlite_data_source) -> None:
    """First user message should replace the raw session id title fallback."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    client = TestClient(
        create_app(
            job_runner=InMemoryJobRunner(data_source=sqlite_data_source, app_config=config),
            app_config=config,
        )
    )

    response = client.post(
        "/sessions/title-rule/chat",
        json={"message": "近 12 个月销售趋势怎么样？"},
    )
    session = client.get("/sessions/title-rule").json()

    assert response.status_code == 200
    assert session["title"] != "title-rule"
    assert session["title"] != "新对话"
    assert session["title_source"] == SessionTitleSource.RULE.value
    assert len(session["title"]) <= 20


def test_fake_llm_can_generate_short_session_title(tmp_path, sqlite_data_source) -> None:
    """fake_llm mode should allow deterministic LLM title generation for analysis chats."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))

    client.post(
        "/sessions/title-fake/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["planner"]},
    )
    response = client.post(
        "/sessions/title-fake/chat",
        json={"message": "近 12 个月销售趋势怎么样？"},
    )
    session = client.get("/sessions/title-fake").json()

    assert response.status_code == 200
    assert session["title_source"] == SessionTitleSource.LLM.value
    assert session["title"]
    assert len(session["title"]) <= 20


def test_fake_llm_title_is_skipped_for_help_message(tmp_path, sqlite_data_source) -> None:
    """Greetings should stay in clarification flow and not call LLM title generation."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))

    client.post(
        "/sessions/title-help/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["planner", "sql_drafter"]},
    )
    response = client.post("/sessions/title-help/chat", json={"message": "hi"})
    session = client.get("/sessions/title-help").json()

    assert response.status_code == 200
    assert response.json()["intent"] == "clarification"
    assert session["title_source"] == SessionTitleSource.RULE.value
    assert client.get("/sessions/title-help/llm").json()["last_llm_call_count"] == 1
