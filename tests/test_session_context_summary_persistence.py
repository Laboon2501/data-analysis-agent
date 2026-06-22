"""Persistence coverage for AgentContextSummary in session stores."""

from app.sessions import SQLAlchemySessionStore
from schemas.context_summary import AgentContextSummary


def test_sqlalchemy_session_store_persists_context_summary(tmp_path) -> None:
    """SQLite session store should restore compact context after reopen."""

    db_path = tmp_path / "sessions.sqlite"
    url = f"sqlite:///{db_path}"
    store = SQLAlchemySessionStore(url=url)
    store.create_session(session_id="ctx-session")
    store.update_context_summary(
        "ctx-session",
        AgentContextSummary(
            session_id="ctx-session",
            current_datasource_id="demo",
            known_tables=["orders"],
            known_fields=["orders.gmv"],
            last_user_intent="schema_qa",
            latest_artifact_refs=["artifact:chart-1"],
        ),
    )

    reopened = SQLAlchemySessionStore(url=url)
    record = reopened.get_session("ctx-session")

    assert record is not None
    assert record.context_summary is not None
    assert record.context_summary.current_datasource_id == "demo"
    assert record.context_summary.known_fields == ["orders.gmv"]
    assert record.context_summary.latest_artifact_refs == ["artifact:chart-1"]
