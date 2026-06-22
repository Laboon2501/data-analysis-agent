"""User-visible stage text_delta events."""

from __future__ import annotations

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner, JobStatus
from schemas.event import EventType


def test_direct_analysis_emits_user_visible_progress_text(sqlite_data_source) -> None:
    """Long-running analysis should stream bounded Chinese progress messages."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="streaming",
        user_message="Show monthly revenue trend",
        datasource_id=sqlite_data_source.datasource_id,
    )

    job = runner.submit_job(state)

    assert job.status is JobStatus.COMPLETED
    messages = [
        event.message
        for event in runner.list_events(job.job_id)
        if event.event_type is EventType.TEXT_DELTA
    ]
    assert "正在理解问题..." in messages
    assert "正在读取数据源画像..." in messages
    assert "正在生成分析计划..." in messages
    assert "正在生成并校验 SQL..." in messages
    assert "正在执行查询..." in messages
    assert "正在生成图表和结论..." in messages
