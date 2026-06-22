"""LLM config API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from llm.base import LLMResponse


def test_llm_config_api_saves_and_status_is_sanitized(tmp_path, sqlite_data_source) -> None:
    """Saving provider config should update status without exposing the key."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm_config.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))

    response = client.post(
        "/llm/config",
        json={
            "provider": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "test-api-key-secret",
            "enabled_nodes": ["planner", "sql_drafter"],
        },
    )
    status = client.get("/llm/status")
    session_response = client.post(
        "/sessions/session-real/llm",
        json={"mode": "real_llm", "enabled_nodes": ["planner"]},
    )

    assert response.status_code == 200
    assert "test-api-key-secret" not in response.text
    assert response.json()["api_key_configured"] is True
    assert status.json()["provider"] == "deepseek"
    assert status.json()["model"] == "deepseek-chat"
    assert status.json()["api_key_configured"] is True
    assert "test-api-key-secret" not in status.text
    assert session_response.status_code == 200
    assert session_response.json()["mode"] == "real_llm"


def test_llm_test_endpoint_uses_mocked_provider_without_leaking_key(
    tmp_path,
    monkeypatch,
) -> None:
    """Connection test should be manually callable and sanitized."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm_config.json"))
    client = TestClient(create_app(app_config=config))

    def fake_complete(self, messages, *, model=None, temperature=None, timeout_seconds=None):
        return LLMResponse(content='{"ok":true}', model=model or "mock")

    monkeypatch.setattr("app.api.main.OpenAICompatibleClient.complete", fake_complete)

    response = client.post(
        "/llm/test",
        json={
            "provider": "openai_compatible",
            "model": "mock-model",
            "base_url": "https://llm.example.test/v1",
            "api_key": "test-api-key-value",
            "enabled_nodes": ["insight_writer"],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["base_url_host"] == "llm.example.test"
    assert "test-api-key-value" not in response.text


def test_real_llm_session_requires_saved_config(tmp_path, sqlite_data_source) -> None:
    """real_llm mode should fail clearly when no provider key/model is configured."""

    config = AppConfig(llm_config_path=str(tmp_path / "missing.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))

    response = client.post(
        "/sessions/no-config/llm",
        json={"mode": "real_llm", "enabled_nodes": ["planner"]},
    )

    assert response.status_code == 400
    assert "missing_model" in response.json()["detail"]
    assert "missing_api_key" in response.json()["detail"]
    assert "sk-" not in response.text


def test_real_llm_session_uses_saved_provider_config(tmp_path, sqlite_data_source) -> None:
    """Session real_llm save should read the persisted provider config store."""

    config = AppConfig(llm_config_path=str(tmp_path / "saved-provider.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))

    save_response = client.post(
        "/llm/config",
        json={
            "provider": "openai_compatible",
            "model": "configured-model",
            "base_url": "https://llm.example.test/v1",
            "api_key": "test-saved-provider-secret",
            "enabled_nodes": ["planner", "sql_drafter", "insight_writer"],
        },
    )
    session_response = client.post(
        "/sessions/uses-saved-provider/llm",
        json={
            "mode": "real_llm",
            "enabled_nodes": ["planner", "sql_drafter", "insight_writer"],
        },
    )

    assert save_response.status_code == 200
    assert session_response.status_code == 200
    assert session_response.json()["mode"] == "real_llm"
    assert session_response.json()["model"] == "configured-model"
    assert "test-saved-provider-secret" not in session_response.text


def test_real_llm_session_reports_specific_missing_fields(tmp_path, sqlite_data_source) -> None:
    """Missing real LLM fields should be explicit for the Web UI."""

    config = AppConfig(llm_config_path=str(tmp_path / "missing-fields.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    client = TestClient(create_app(job_runner=runner, app_config=config))
    client.post(
        "/llm/config",
        json={
            "provider": "openai_compatible",
            "model": "",
            "base_url": "https://llm.example.test/v1",
            "enabled_nodes": ["planner"],
        },
    )

    response = client.post(
        "/sessions/missing-fields/llm",
        json={"mode": "real_llm", "enabled_nodes": ["planner"]},
    )

    assert response.status_code == 400
    assert "missing_model" in response.json()["detail"]
    assert "missing_api_key" in response.json()["detail"]
    assert "sk-" not in response.text
