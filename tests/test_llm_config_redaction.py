"""Regression tests that LLM secrets stay out of API-visible runtime data."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.sessions import InMemorySessionStore
from app.workers import InMemoryJobRunner


def test_saved_llm_key_does_not_leak_to_status_events_or_history(
    tmp_path,
    sqlite_data_source,
) -> None:
    """The raw API key must not appear in loggable API responses."""

    secret = "test-no-leak-phase48"
    config = AppConfig(llm_config_path=str(tmp_path / "llm_config.json"))
    runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=config)
    session_store = InMemorySessionStore()
    client = TestClient(
        create_app(job_runner=runner, session_store=session_store, app_config=config)
    )

    save_response = client.post(
        "/llm/config",
        json={
            "provider": "openai_compatible",
            "model": "mock-model",
            "base_url": "https://llm.example.test/v1",
            "api_key": secret,
            "enabled_nodes": ["planner"],
        },
    )
    chat_response = client.post("/sessions/secret-session/chat", json={"message": "hi"})
    job_id = chat_response.json()["job_id"]

    public_responses = [
        save_response.text,
        client.get("/llm/config").text,
        client.get("/llm/status").text,
        client.get("/health/runtime").text,
        client.get(f"/jobs/{job_id}/events").text,
        client.get("/sessions/secret-session/messages").text,
        client.get("/sessions/secret-session").text,
    ]

    assert chat_response.status_code == 200
    assert all(secret not in payload for payload in public_responses)
    assert all("test-no-leak" not in payload for payload in public_responses)
