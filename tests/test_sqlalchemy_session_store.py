"""SQLAlchemy session store persistence tests."""

from __future__ import annotations

import json
import sqlite3

from app.llm_runtime import LLMRuntimeMode
from app.sessions import ChatRole, SessionJobSummary, SQLAlchemySessionStore
from schemas._base import utc_now


def test_sqlite_session_store_persists_after_reopen(tmp_path) -> None:
    """SQLite store should keep sessions, messages, jobs, refs, datasource, and LLM config."""

    db_url = f"sqlite:///{tmp_path / 'sessions.sqlite'}"
    first = SQLAlchemySessionStore(url=db_url)
    first.create_session(session_id="persist-a", title="Persistent")
    first.update_session_datasource("persist-a", "demo")
    first.update_session_llm_config(
        "persist-a",
        mode=LLMRuntimeMode.FAKE_LLM,
        enabled_nodes=["planner", "sql_drafter"],
    )
    first.add_message(
        "persist-a",
        role=ChatRole.USER,
        content="Show trend",
        artifact_refs=["artifact:chart-1"],
        metadata={"safe": True},
    )
    first.record_job(
        SessionJobSummary(
            job_id="job-1",
            session_id="persist-a",
            status="completed",
            intent="direct_analysis",
            command="analyze",
            created_at=utc_now(),
            updated_at=utc_now(),
            artifact_refs=["artifact:chart-2"],
        )
    )

    second = SQLAlchemySessionStore(url=db_url)
    record = second.get_session("persist-a")
    messages = second.list_messages("persist-a")
    jobs = second.list_jobs("persist-a")

    assert record is not None
    assert record.title == "Persistent"
    assert record.datasource_id == "demo"
    assert record.llm_mode is LLMRuntimeMode.FAKE_LLM
    assert record.enabled_llm_nodes == ["planner", "sql_drafter"]
    assert record.artifact_refs == ["artifact:chart-1", "artifact:chart-2"]
    assert messages[0].content == "Show trend"
    assert messages[0].metadata == {"safe": True}
    assert jobs[0].job_id == "job-1"


def test_sqlite_session_store_does_not_persist_artifact_body_or_api_key(tmp_path) -> None:
    """History persistence should not store large artifact bodies or secrets."""

    db_path = tmp_path / "sessions.sqlite"
    store = SQLAlchemySessionStore(url=f"sqlite:///{db_path}")

    store.add_message(
        "safe-a",
        role=ChatRole.ASSISTANT,
        content="artifact ready",
        artifact_refs=["artifact:report-1"],
        metadata={
            "artifact_ref": "artifact:report-1",
            "api_key_configured": True,
            "note": "no raw secret",
        },
    )

    raw_bytes = db_path.read_bytes()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")
    serialized_history = json.dumps(
        {
            "sessions": [record.model_dump(mode="json") for record in store.list_sessions()],
            "messages": [
                message.model_dump(mode="json") for message in store.list_messages("safe-a")
            ],
        }
    )

    assert "artifact:report-1" in serialized_history
    assert "<html" not in raw_text.lower()
    assert "file_bytes" not in raw_text
    assert "sk-" not in raw_text


def test_sqlite_session_store_adds_new_context_columns_to_existing_db(tmp_path) -> None:
    """Older local SQLite stores should gain latest-context columns on open."""

    db_path = tmp_path / "legacy_sessions.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE session_records (
                session_id VARCHAR(255) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                summary TEXT,
                title_source VARCHAR(32) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                datasource_id VARCHAR(255),
                llm_mode VARCHAR(64) NOT NULL,
                enabled_llm_nodes_json TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                last_message_preview TEXT,
                artifact_refs_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE session_job_summaries (
                job_id VARCHAR(255) PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                status VARCHAR(64) NOT NULL,
                intent VARCHAR(64) NOT NULL,
                command VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                final_response_text TEXT,
                error_message TEXT,
                needs_human BOOLEAN NOT NULL,
                artifact_refs_json TEXT NOT NULL
            )
            """
        )

    store = SQLAlchemySessionStore(url=f"sqlite:///{db_path}")
    store.record_job(
        SessionJobSummary(
            job_id="job-report",
            session_id="legacy-session",
            status="completed",
            intent="report_export",
            command="ppt_confirm",
            created_at=utc_now(),
            updated_at=utc_now(),
            artifact_refs=["artifact:ppt-1"],
            analysis_package_id="package-1",
            report_outline_id="outline-1",
            ppt_artifact_ref="artifact:ppt-1",
        )
    )

    record = store.get_session("legacy-session")

    assert record is not None
    assert record.latest_analysis_package_id == "package-1"
    assert record.latest_report_outline_id == "outline-1"
    assert record.latest_ppt_artifact_ref == "artifact:ppt-1"
