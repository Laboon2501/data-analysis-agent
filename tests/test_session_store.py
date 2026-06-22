"""Session history store unit tests."""

from __future__ import annotations

from app.llm_runtime import LLMRuntimeMode
from app.sessions import (
    ChatRole,
    InMemorySessionStore,
    SessionJobSummary,
    extract_artifact_refs,
)
from schemas._base import utc_now


def test_session_store_create_list_read_delete() -> None:
    """Memory store should support the basic session lifecycle."""

    store = InMemorySessionStore()

    created = store.create_session(session_id="session-a", title="Demo")
    listed = store.list_sessions()
    deleted = store.delete_session("session-a")

    assert created.session_id == "session-a"
    assert listed[0].title == "Demo"
    assert deleted is True
    assert store.get_session("session-a") is None


def test_session_store_records_messages_and_preview() -> None:
    """Messages should update message_count and last preview."""

    store = InMemorySessionStore()

    message = store.add_message(
        "session-a",
        role=ChatRole.USER,
        content="Show monthly revenue trend",
        job_id="job-1",
    )
    record = store.get_session("session-a")

    assert message.role is ChatRole.USER
    assert record is not None
    assert record.message_count == 1
    assert record.title == "Show monthly revenue trend"
    assert record.last_message_preview == "Show monthly revenue trend"


def test_session_store_records_job_artifact_refs_without_content() -> None:
    """Job summaries should keep only artifact references."""

    store = InMemorySessionStore()
    store.record_job(
        SessionJobSummary(
            job_id="job-1",
            session_id="session-a",
            status="completed",
            intent="direct_analysis",
            command="analyze",
            created_at=utc_now(),
            updated_at=utc_now(),
            artifact_refs=["artifact:chart-1", "chart-1"],
        )
    )

    record = store.get_session("session-a")
    jobs = store.list_jobs("session-a")

    assert record is not None
    assert record.artifact_refs == ["artifact:chart-1"]
    assert jobs[0].artifact_refs == ["artifact:chart-1"]


def test_session_store_tracks_datasource_and_llm_config() -> None:
    """Datasource and LLM settings are summarized per session."""

    store = InMemorySessionStore()

    store.set_datasource("session-a", "demo")
    store.set_llm_config(
        "session-a",
        mode=LLMRuntimeMode.FAKE_LLM,
        enabled_nodes=["planner", "sql_drafter"],
    )
    record = store.get_session("session-a")

    assert record is not None
    assert record.datasource_id == "demo"
    assert record.llm_mode is LLMRuntimeMode.FAKE_LLM
    assert record.enabled_llm_nodes == ["planner", "sql_drafter"]


def test_extract_artifact_refs_ignores_large_content_fields() -> None:
    """Artifact extraction should not treat body content as history data."""

    refs = extract_artifact_refs(
        {
            "artifact_ref": "artifact:report-1",
            "content": "<html>large body</html>",
            "children": [{"artifact_id": "chart-2", "file_bytes": "abc"}],
        }
    )

    assert refs == ["artifact:report-1", "artifact:chart-2"]
