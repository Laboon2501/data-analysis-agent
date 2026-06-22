"""Secret-leak checks for compact context summary."""

from app.context_summary import compact_context_summary
from schemas import AgentCommand, AgentIntent, AgentState


def test_context_summary_does_not_persist_api_key_text() -> None:
    """Context summary must redact secret-looking values before persistence."""

    state = AgentState(
        session_id="secret-session",
        job_id="secret-job",
        user_message="请记住 bearer demo-token",
        command=AgentCommand.NONE,
        intent=AgentIntent.CLARIFICATION,
    )

    dumped = compact_context_summary(state).model_dump_json()

    assert "demo-token" not in dumped
    assert "[secret]" in dumped
