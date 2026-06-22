"""Regression tests that LLM responders do not receive free tool access."""

from app.llm_runtime import LLMRuntimeMode, SessionLLMConfig
from app.workers import InMemoryJobRunner
from schemas import AgentCommand, AgentIntent, AgentState, EventType


def test_schema_qa_llm_path_does_not_emit_tool_events(sqlite_data_source) -> None:
    """Schema QA LLM answer writing must not expose ToolRegistry or MCP tools."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    runner.set_session_llm_config(
        "schema-no-tools",
        SessionLLMConfig(mode=LLMRuntimeMode.FAKE_LLM, enabled_nodes=["planner"]),
    )
    job = runner.submit_job(
        AgentState(
            session_id="schema-no-tools",
            job_id="schema-no-tools-job",
            user_message="有哪些字段",
            command=AgentCommand.SCHEMA_QA,
            intent=AgentIntent.SCHEMA_QA,
            datasource_id=sqlite_data_source.datasource_id,
        )
    )

    assert job.status.value == "completed"
    assert job.final_state is not None
    assert job.final_state.sql_result is None
    events = runner.list_events(job.job_id)
    event_types = {event.event_type for event in events}
    assert EventType.LLM_START in event_types
    assert EventType.TOOL_START not in event_types
    assert EventType.TOOL_END not in event_types
    assert "mcp__" not in str([event.model_dump(mode="json") for event in events])
    assert "query_data" not in str([event.model_dump(mode="json") for event in events])
