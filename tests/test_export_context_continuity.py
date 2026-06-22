"""API-level export context continuity tests."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from persistence import InMemoryArtifactStore


def test_report_then_ppt_reuses_latest_session_context(sqlite_data_source) -> None:
    """分析后生成报告，再说“帮我做成 PPT”应复用同一 session 上下文。"""

    artifact_store = InMemoryArtifactStore()
    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        artifact_store=artifact_store,
    )
    client = TestClient(create_app(job_runner=runner))

    analysis_job = client.post(
        "/sessions/session-continuity/chat",
        json={"message": "Show monthly revenue trend"},
    ).json()
    report_job = client.post(
        "/sessions/session-continuity/chat",
        json={"message": "继续生成报告"},
    ).json()
    ppt_job = client.post(
        "/sessions/session-continuity/chat",
        json={"message": "帮我做成 PPT"},
    ).json()

    assert analysis_job["status"] == "completed"
    assert report_job["status"] == "completed"
    assert report_job["command"] == "report_confirm"
    assert report_job["final_state"]["report_result"]["artifact_ref"].startswith("artifact:")
    assert ppt_job["status"] == "completed"
    assert ppt_job["command"] == "ppt_confirm"
    assert ppt_job["final_state"]["report_result"]["artifact_ref"].startswith("artifact:")
    assert "缺少分析结果" not in str(ppt_job)
    assert "Node '" not in str(ppt_job)

    session = client.get("/sessions/session-continuity").json()
    assert session["latest_analysis_package_id"]
    assert session["latest_report_artifact_ref"].startswith("artifact:")
    assert session["latest_ppt_artifact_ref"].startswith("artifact:")
    assert session["latest_exportable_job_id"] == ppt_job["job_id"]


def test_excel_and_dashboard_reuse_latest_analysis_package(sqlite_data_source) -> None:
    """Excel 和 Dashboard follow-up 也应复用最近一次分析结果。"""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner))

    client.post(
        "/sessions/session-export/chat",
        json={"message": "Show monthly revenue trend"},
    )
    excel_job = client.post(
        "/sessions/session-export/chat",
        json={"message": "导出 Excel"},
    ).json()
    dashboard_job = client.post(
        "/sessions/session-export/chat",
        json={"message": "做成 Dashboard"},
    ).json()

    assert excel_job["status"] == "completed"
    assert excel_job["command"] == "excel_confirm"
    assert dashboard_job["status"] == "completed"
    assert dashboard_job["command"] == "dashboard_confirm"
