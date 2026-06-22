"""User-visible export error handling tests."""

from app.workers import InMemoryJobRunner, JobStatus
from schemas import AgentCommand, AgentIntent, AgentState


def test_report_confirm_without_analysis_package_returns_chinese_error() -> None:
    """缺少分析包时，普通用户不应看到底层 NodeExecutionError 文案。"""

    runner = InMemoryJobRunner()
    state = AgentState(
        session_id="session-1",
        job_id="job-missing-package",
        user_message="report_confirm",
        command=AgentCommand.REPORT_CONFIRM,
        intent=AgentIntent.REPORT_EXPORT,
    )

    job = runner.submit_job(state)

    assert job.status is JobStatus.FAILED
    assert job.error_message == "当前会话没有可复用的分析结果，请先完成一次分析或开放探索。"
    assert "Node '" not in job.error_message
    assert job.final_state is not None
    assert job.final_state.final_response_text == job.error_message
    assert job.final_state.errors[-1].code == "export_missing_analysis_package"

    events = runner.list_events(job.job_id)
    job_error_event = events[-1]
    assert job_error_event.event_type.value == "error"
    assert job_error_event.message == job.error_message
    assert job_error_event.payload["code"] == "export_missing_analysis_package"
    assert str(job_error_event.payload["raw_error"]).startswith("Node 'analysis_package' failed")
