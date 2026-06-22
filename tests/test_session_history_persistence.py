"""API-level persistence checks for visible chat history and LLM rollout."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.sessions import SQLAlchemySessionStore
from app.workers import InMemoryJobRunner


def test_sqlite_session_store_restores_chat_history_and_llm_config(
    sqlite_data_source,
    tmp_path,
) -> None:
    """SQLite session store should survive API restarts for ordinary chat."""

    db_url = f"sqlite:///{tmp_path / 'sessions.sqlite'}"
    app_config = AppConfig(llm_config_path=str(tmp_path / "llm.json"))
    first_store = SQLAlchemySessionStore(url=db_url)
    first_runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=app_config)
    first_client = TestClient(
        create_app(
            job_runner=first_runner,
            session_store=first_store,
            app_config=app_config,
        )
    )
    set_response = first_client.post(
        "/sessions/persist-chat/llm",
        json={"mode": "fake_llm", "enabled_nodes": ["planner"]},
    )
    chat_response = first_client.post(
        "/sessions/persist-chat/chat",
        json={"message": "啊？"},
    )

    assert set_response.status_code == 200
    assert chat_response.status_code == 200
    assert first_client.get("/sessions/persist-chat/llm").json()["last_llm_call_count"] == 1

    second_store = SQLAlchemySessionStore(url=db_url)
    second_runner = InMemoryJobRunner(data_source=sqlite_data_source, app_config=app_config)
    second_client = TestClient(
        create_app(
            job_runner=second_runner,
            session_store=second_store,
            app_config=app_config,
        )
    )

    messages = second_client.get("/sessions/persist-chat/messages").json()
    restored_status = second_client.get("/sessions/persist-chat/llm").json()
    model_response = second_client.post(
        "/sessions/persist-chat/chat",
        json={"message": "你是什么模型？"},
    )

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "啊？"
    assert restored_status["mode"] == "fake_llm"
    assert restored_status["enabled_nodes"] == ["planner"]
    assert model_response.status_code == 200
    assert second_client.get("/sessions/persist-chat/llm").json()["last_llm_call_count"] == 1
    session = second_client.get("/sessions/persist-chat").json()
    assert session["message_count"] == 4
    serialized = str(messages) + str(model_response.json())
    assert "api_key" not in serialized.lower()
    assert "sk-" not in serialized
