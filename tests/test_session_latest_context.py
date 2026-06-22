"""Session latest export context tests."""

from app.sessions import InMemorySessionStore, SessionJobSummary
from schemas._base import utc_now


def test_session_record_tracks_latest_export_context_refs() -> None:
    """SessionStore 只保存 latest context 的小引用，不保存正文。"""

    store = InMemorySessionStore()
    now = utc_now()
    store.record_job(
        SessionJobSummary(
            job_id="job-report",
            session_id="session-latest",
            status="completed",
            intent="report_export",
            command="report_confirm",
            created_at=now,
            updated_at=now,
            final_response_text="报告 已生成：artifact:report-1",
            artifact_refs=["artifact:report-1"],
            analysis_package_id="package-1",
            report_outline_id="outline-1",
            report_artifact_ref="artifact:report-1",
        )
    )

    record = store.get_session("session-latest")

    assert record is not None
    assert record.latest_analysis_package_id == "package-1"
    assert record.latest_report_outline_id == "outline-1"
    assert record.latest_report_artifact_ref == "artifact:report-1"
    assert record.latest_exportable_job_id == "job-report"
    assert record.artifact_refs == ["artifact:report-1"]
    assert "PK\x03\x04" not in str(record.model_dump(mode="json"))
