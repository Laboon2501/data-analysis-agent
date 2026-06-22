"""PPT follow-up after report export tests."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner


def test_ppt_after_report_does_not_require_user_to_resend_package(sqlite_data_source) -> None:
    """生成 report artifact 后，PPT follow-up 不应要求用户重新提供分析结果。"""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))

    client.post(
        "/sessions/session-ppt/chat",
        json={"message": "Show monthly revenue trend"},
    )
    report_job = client.post(
        "/sessions/session-ppt/chat",
        json={"message": "继续生成报告"},
    ).json()
    ppt_job = client.post(
        "/sessions/session-ppt/chat",
        json={"message": "转成 PPT"},
    ).json()

    assert report_job["status"] == "completed"
    assert report_job["command"] == "report_confirm"
    assert ppt_job["status"] == "completed"
    assert ppt_job["command"] == "ppt_confirm"
    assert ppt_job["error_message"] is None
