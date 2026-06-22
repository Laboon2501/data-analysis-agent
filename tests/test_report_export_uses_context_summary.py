"""Report/export continuity should update compact session context."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner


def test_completed_analysis_updates_context_summary_for_export(sqlite_data_source) -> None:
    """分析完成后 session summary 应记录可复用分析包引用。"""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))
    response = client.post(
        "/sessions/export-context/chat",
        json={"message": "What is total revenue?"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    session = client.get("/sessions/export-context").json()

    context_summary = session["context_summary"]
    assert context_summary["last_user_intent"] == "direct_analysis"
    assert context_summary["latest_analysis_package_id"]
    assert context_summary["last_sql_summary"]["validated"] is True
