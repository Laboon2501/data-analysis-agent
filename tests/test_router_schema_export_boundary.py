"""Routing boundaries between schema QA and guarded export commands."""

from app.api.main import _export_continuation_command
from app.harness import infer_command_and_intent
from schemas import AgentCommand, AgentIntent


def test_field_question_with_table_word_routes_to_schema_qa_not_export() -> None:
    """包含“表格”的字段问题不能被误判为 Excel 导出确认。"""

    message = "帮我看看这个表格都有哪些字段"

    command, intent = infer_command_and_intent(message)

    assert command is AgentCommand.SCHEMA_QA
    assert intent is AgentIntent.SCHEMA_QA
    assert _export_continuation_command(message) is None


def test_export_commands_require_explicit_export_intent() -> None:
    """只有明确导出或报告措辞才进入 report/export intent。"""

    assert infer_command_and_intent("生成报告") == (
        AgentCommand.REPORT,
        AgentIntent.REPORT_EXPORT,
    )
    assert infer_command_and_intent("导出 Excel 表格") == (
        AgentCommand.REPORT,
        AgentIntent.REPORT_EXPORT,
    )
    assert _export_continuation_command("导出 Excel 表格") is AgentCommand.EXCEL_CONFIRM


def test_open_exploration_boundary_is_not_schema_qa() -> None:
    """“有什么可以分析”类请求应进入开放探索，而不是字段问答。"""

    command, intent = infer_command_and_intent("这张表有什么可以分析的吗")

    assert command is AgentCommand.EXPLORE
    assert intent is AgentIntent.OPEN_EXPLORATION
