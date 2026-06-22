"""Chat history writeback tests for API jobs."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.sessions import InMemorySessionStore
from app.workers import InMemoryJobRunner


def test_chat_writes_user_and_assistant_messages(sqlite_data_source) -> None:
    """A normal chat job should write visible user and assistant history."""

    client = _client(sqlite_data_source)

    response = client.post(
        "/sessions/session-history/chat",
        json={"message": "What is total revenue?"},
    )
    messages = client.get("/sessions/session-history/messages").json()
    session = client.get("/sessions/session-history").json()

    assert response.status_code == 200
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is total revenue?"
    assert messages[1]["content"] == response.json()["final_response_text"]
    assert session["message_count"] == 2
    assert session["last_message_preview"] == response.json()["final_response_text"]


def test_hi_help_writes_history_but_does_not_execute_sql(sqlite_data_source) -> None:
    """Clarification messages should be persisted without SQL artifacts."""

    client = _client(sqlite_data_source)

    response = client.post("/sessions/session-hi/chat", json={"message": "hi"})
    messages = client.get("/sessions/session-hi/messages").json()
    jobs = client.get("/sessions/session-hi/jobs").json()

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_result"] is None
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hi"
    assert jobs[0]["intent"] == "clarification"


def test_artifact_refs_enter_session_without_artifact_content(sqlite_data_source) -> None:
    """Chart artifacts should be referenced in history without embedding bodies."""

    client = _client(sqlite_data_source)

    response = client.post(
        "/sessions/session-artifact/chat",
        json={"message": "Show monthly revenue trend"},
    )
    session = client.get("/sessions/session-artifact").json()
    messages = client.get("/sessions/session-artifact/messages").json()
    jobs = client.get("/sessions/session-artifact/jobs").json()
    serialized = json.dumps({"session": session, "messages": messages, "jobs": jobs})

    assert response.status_code == 200
    assert session["artifact_refs"]
    assert jobs[0]["artifact_refs"] == session["artifact_refs"]
    assert messages[-1]["artifact_refs"] == session["artifact_refs"]
    assert "chart_html" not in serialized
    assert "file_bytes" not in serialized
    assert "data_url" not in serialized
    assert "<html" not in serialized.lower()


def _client(sqlite_data_source) -> TestClient:
    """Build an API client with isolated session history."""

    return TestClient(
        create_app(
            job_runner=InMemoryJobRunner(data_source=sqlite_data_source),
            session_store=InMemorySessionStore(),
        )
    )
