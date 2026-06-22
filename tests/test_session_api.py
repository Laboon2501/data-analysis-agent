"""Session list and history API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.llm_runtime import LLMRuntimeMode
from app.sessions import InMemorySessionStore, SQLAlchemySessionStore
from app.workers import InMemoryJobRunner


def test_session_api_create_list_read_messages_and_delete() -> None:
    """Session API should expose lifecycle and message endpoints."""

    store = InMemorySessionStore()
    client = TestClient(create_app(session_store=store))

    create_response = client.post(
        "/sessions",
        json={"session_id": "session-a", "title": "Session A"},
    )
    message_response = client.post(
        "/sessions/session-a/messages",
        json={"role": "user", "content": "hello"},
    )
    list_response = client.get("/sessions")
    get_response = client.get("/sessions/session-a")
    messages_response = client.get("/sessions/session-a/messages")
    delete_response = client.delete("/sessions/session-a")
    missing_response = client.get("/sessions/session-a")

    assert create_response.status_code == 200
    assert create_response.json()["title"] == "Session A"
    assert message_response.status_code == 200
    assert list_response.json()[0]["session_id"] == "session-a"
    assert get_response.json()["message_count"] == 1
    assert messages_response.json()[0]["content"] == "hello"
    assert delete_response.status_code == 200
    assert missing_response.status_code == 404


def test_session_api_tracks_datasource_selection(sqlite_data_source) -> None:
    """Session record should update when datasource selection changes."""

    store = InMemorySessionStore()
    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner, session_store=store))

    response = client.post(
        "/sessions/session-a/datasource",
        json={"datasource_id": sqlite_data_source.datasource_id},
    )
    session_response = client.get("/sessions/session-a")

    assert response.status_code == 200
    assert session_response.status_code == 200
    assert session_response.json()["datasource_id"] == sqlite_data_source.datasource_id


def test_session_api_tracks_llm_config(sqlite_data_source) -> None:
    """Session record should update when LLM mode and nodes change."""

    store = InMemorySessionStore()
    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner, session_store=store))

    response = client.post(
        "/sessions/session-a/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["planner", "sql_drafter"]},
    )
    session_response = client.get("/sessions/session-a")

    assert response.status_code == 200
    assert session_response.status_code == 200
    assert session_response.json()["llm_mode"] == LLMRuntimeMode.FAKE_LLM.value
    assert session_response.json()["enabled_llm_nodes"] == ["planner", "sql_drafter"]


def test_session_jobs_endpoint_returns_chat_job_summary(sqlite_data_source) -> None:
    """Chat jobs should be visible from the session jobs endpoint."""

    store = InMemorySessionStore()
    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner, session_store=store))

    job_response = client.post(
        "/sessions/session-a/chat",
        json={"message": "What is total revenue?"},
    )
    jobs_response = client.get("/sessions/session-a/jobs")

    assert job_response.status_code == 200
    assert jobs_response.status_code == 200
    jobs = jobs_response.json()
    assert jobs[0]["job_id"] == job_response.json()["job_id"]
    assert jobs[0]["status"] == "completed"
    assert jobs[0]["intent"] == "direct_analysis"


def test_session_cleanup_endpoint_trims_messages() -> None:
    """Manual cleanup endpoint should trim old messages without changing routes."""

    store = InMemorySessionStore()
    client = TestClient(create_app(session_store=store))
    for index in range(3):
        client.post(
            "/sessions/session-a/messages",
            json={"role": "user", "content": f"message-{index}"},
        )

    response = client.post("/sessions/cleanup", json={"max_messages": 1})
    messages = client.get("/sessions/session-a/messages").json()
    session = client.get("/sessions/session-a").json()

    assert response.status_code == 200
    assert response.json()["trimmed_messages"] == 2
    assert [message["content"] for message in messages] == ["message-2"]
    assert session["message_count"] == 1


def test_session_api_can_use_sqlite_persistent_store(tmp_path) -> None:
    """Session API should work with the SQLAlchemy-backed SQLite store."""

    db_url = f"sqlite:///{tmp_path / 'sessions.sqlite'}"
    store = SQLAlchemySessionStore(url=db_url)
    client = TestClient(create_app(session_store=store))

    client.post("/sessions", json={"session_id": "persist-api", "title": "Persist API"})
    client.post(
        "/sessions/persist-api/messages",
        json={"role": "user", "content": "hello", "artifact_refs": ["artifact:chart-1"]},
    )

    reopened = SQLAlchemySessionStore(url=db_url)
    assert reopened.get_session("persist-api").artifact_refs == ["artifact:chart-1"]
    assert reopened.list_messages("persist-api")[0].content == "hello"


def test_session_delete_last_leaves_session_list_empty() -> None:
    """Deleting the last session should not recreate it on the backend."""

    store = InMemorySessionStore()
    client = TestClient(create_app(session_store=store))

    client.post("/sessions", json={"session_id": "only-session", "title": "Only"})
    delete_response = client.delete("/sessions/only-session")
    list_response = client.get("/sessions")

    assert delete_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json() == []
