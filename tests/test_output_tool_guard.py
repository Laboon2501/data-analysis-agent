"""Tests for export tool confirmation guard rules."""

import pytest

from guards.output_tool_guard import EXPORT_TOOL_CONFIRM_COMMANDS, check_output_tool_allowed
from schemas.agent_state import AgentCommand


def test_non_export_tool_is_allowed_without_confirm_command() -> None:
    """Ordinary tools should not require export confirmation commands."""

    result = check_output_tool_allowed("read_schema", AgentCommand.NONE)

    assert result.allowed is True
    assert result.required_command is None


@pytest.mark.parametrize("tool_name,required_command", EXPORT_TOOL_CONFIRM_COMMANDS.items())
def test_export_tools_are_blocked_without_matching_confirm_command(
    tool_name: str,
    required_command: AgentCommand,
) -> None:
    """Export tools must not run from ordinary chat commands."""

    result = check_output_tool_allowed(tool_name, AgentCommand.ANALYZE)

    assert result.allowed is False
    assert result.required_command is required_command
    assert result.errors


@pytest.mark.parametrize("tool_name,required_command", EXPORT_TOOL_CONFIRM_COMMANDS.items())
def test_export_tools_are_allowed_with_matching_confirm_command(
    tool_name: str,
    required_command: AgentCommand,
) -> None:
    """The matching fast-path confirm command should allow the export tool."""

    result = check_output_tool_allowed(tool_name, required_command)

    assert result.allowed is True
    assert result.required_command is required_command
