"""User-facing export error message regressions."""

from app.workers import InMemoryJobRunner, JobStatus
from schemas import AgentCommand, AgentIntent, AgentState


def test_export_missing_context_error_is_business_facing_chinese() -> None:
    """缺少导出上下文时，普通用户不应看到节点包装错误。"""

    runner = InMemoryJobRunner()
    job = runner.submit_job(
        AgentState(
            session_id="session-error",
            job_id="job-error",
            user_message="帮我做成 PPT",
            command=AgentCommand.PPT_CONFIRM,
            intent=AgentIntent.REPORT_EXPORT,
        )
    )

    assert job.status is JobStatus.FAILED
    assert job.error_message == "当前会话没有可复用的分析结果，请先完成一次分析或开放探索。"
    assert "Node '" not in job.error_message
    assert job.final_state is not None
    assert job.final_state.errors[-1].code == "export_missing_analysis_package"
