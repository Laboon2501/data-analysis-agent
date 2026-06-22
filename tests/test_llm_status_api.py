"""LLM runtime status API tests."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner


def test_llm_status_defaults_to_rule_without_api_key(monkeypatch, tmp_path) -> None:
    """Default status must be safe, local, and credential-free."""

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    client = TestClient(create_app(job_runner=InMemoryJobRunner(app_config=config)))

    response = client.get("/llm/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "rule"
    assert payload["enabled_nodes"] == []
    assert payload["api_key_configured"] is False
    assert "api_key" not in json.dumps(payload).replace("api_key_configured", "")


def test_llm_status_does_not_leak_configured_api_key(monkeypatch, tmp_path) -> None:
    """The API may report key presence but must never return the raw value."""

    monkeypatch.setenv("PHASE37_LLM_KEY", "test-secret-phase37")
    config = AppConfig(
        llm_provider="openai_compatible",
        llm_model="gpt-test",
        llm_base_url="https://api.example.test/v1",
        llm_api_key_env="PHASE37_LLM_KEY",
        llm_config_path=str(tmp_path / "llm.json"),
    )
    client = TestClient(create_app(job_runner=InMemoryJobRunner(app_config=config)))

    response = client.get("/llm/status")

    assert response.status_code == 200
    payload_text = json.dumps(response.json())
    assert response.json()["api_key_configured"] is True
    assert "test-secret-phase37" not in payload_text
    assert "api.example.test" in payload_text


def test_enabling_real_llm_without_api_key_returns_clear_error(monkeypatch, tmp_path) -> None:
    """real_llm mode requires backend environment configuration."""

    monkeypatch.delenv("MISSING_PHASE37_LLM_KEY", raising=False)
    config = AppConfig(
        llm_provider="openai_compatible",
        llm_model="gpt-test",
        llm_api_key_env="MISSING_PHASE37_LLM_KEY",
        llm_config_path=str(tmp_path / "llm.json"),
    )
    client = TestClient(create_app(job_runner=InMemoryJobRunner(app_config=config)))

    response = client.post(
        "/sessions/session-llm/llm",
        json={"mode": "real_llm", "enabled_nodes": ["planner"]},
    )

    assert response.status_code == 400
    assert "MISSING_PHASE37_LLM_KEY" in response.json()["detail"]


def test_session_llm_config_can_enable_fake_nodes(tmp_path) -> None:
    """Session LLM endpoint should persist mode and normalized node aliases."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    client = TestClient(create_app(job_runner=InMemoryJobRunner(app_config=config)))

    set_response = client.post(
        "/sessions/session-llm/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["planner", "sql_drafter", "planner"]},
    )
    get_response = client.get("/sessions/session-llm/llm")

    assert set_response.status_code == 200
    assert get_response.status_code == 200
    assert set_response.json()["mode"] == "fake_llm"
    assert set_response.json()["enabled_nodes"] == ["planner", "sql_drafter"]
    assert get_response.json()["enabled_nodes"] == ["planner", "sql_drafter"]


def test_session_llm_config_rejects_unknown_node(tmp_path) -> None:
    """Only narrow, known LLM node aliases are accepted."""

    config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    client = TestClient(create_app(job_runner=InMemoryJobRunner(app_config=config)))

    response = client.post(
        "/sessions/session-llm/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["all_tools"]},
    )

    assert response.status_code == 400
    assert "Unsupported LLM node" in response.json()["detail"]
