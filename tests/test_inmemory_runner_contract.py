"""Tests for InMemoryJobRunner through the shared WorkerBackend interface."""

from __future__ import annotations

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner, JobStatus, WorkerBackend
from schemas import AgentCommand, ChartSpec, ChartType, Insight
from schemas.analysis_package import AnalysisPackage
from schemas.event import EventType
from schemas.query_result import QueryColumn, QueryResult


def test_inmemory_runner_submit_job_contract(sqlite_data_source) -> None:
    """submit_job should preserve the existing synchronous in-memory behavior."""

    runner: WorkerBackend = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="session-1",
        user_message="What is total revenue?",
    )

    job = runner.submit_job(state)

    assert job.status is JobStatus.COMPLETED
    assert job.final_state is not None
    assert job.final_state.final_response_text == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"
    assert runner.get_job(job.job_id).status is JobStatus.COMPLETED
    assert [event.event_type for event in runner.stream_events(job.job_id)][-1] is EventType.DONE


def test_inmemory_runner_approve_and_cancel_contract(sqlite_data_source) -> None:
    """approve and cancel should match the old approve_job/cancel_job behavior."""

    runner: WorkerBackend = InMemoryJobRunner(data_source=sqlite_data_source)
    waiting_job_for_approve = runner.submit_job(
        build_initial_state(
            session_id="session-1",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        )
    )
    waiting_job_for_cancel = runner.submit_job(
        build_initial_state(
            session_id="session-2",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        )
    )

    completed_job = runner.approve(waiting_job_for_approve.job_id, AgentCommand.REPORT_CONFIRM)
    cancelled_job = runner.cancel(waiting_job_for_cancel.job_id)

    assert completed_job.status is JobStatus.COMPLETED
    assert completed_job.final_state is not None
    assert completed_job.final_state.report_result is not None
    assert cancelled_job.status is JobStatus.CANCELLED
    assert any(
        event.event_type is EventType.STOPPED
        for event in runner.list_events(waiting_job_for_cancel.job_id)
    )


def _analysis_package() -> AnalysisPackage:
    """Create a minimal package for report fast-path tests."""

    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE, title="Total revenue"),
        insights=[
            Insight(
                title="Revenue summary",
                summary="\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002",
            )
        ],
    )
