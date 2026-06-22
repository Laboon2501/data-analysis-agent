"""Guard rules for export tools that require explicit confirmation commands."""

from __future__ import annotations

from pydantic import Field

from schemas._base import StrictBaseModel
from schemas.agent_state import AgentCommand

EXPORT_TOOL_CONFIRM_COMMANDS: dict[str, AgentCommand] = {
    "export_excel": AgentCommand.EXCEL_CONFIRM,
    "export_report": AgentCommand.REPORT_CONFIRM,
    "generate_ppt": AgentCommand.PPT_CONFIRM,
    "generate_dashboard": AgentCommand.DASHBOARD_CONFIRM,
}


class OutputToolGuardResult(StrictBaseModel):
    """Decision for whether a tool can be called in the current command path."""

    tool_name: str
    command: AgentCommand
    allowed: bool
    required_command: AgentCommand | None = None
    errors: list[str] = Field(default_factory=list)


def check_output_tool_allowed(
    tool_name: str,
    command: AgentCommand | str = AgentCommand.NONE,
) -> OutputToolGuardResult:
    """Allow export tools only when their matching confirm command is active."""

    normalized_command = command if isinstance(command, AgentCommand) else AgentCommand(command)
    required_command = EXPORT_TOOL_CONFIRM_COMMANDS.get(tool_name)

    if required_command is None:
        return OutputToolGuardResult(
            tool_name=tool_name,
            command=normalized_command,
            allowed=True,
        )

    if normalized_command is required_command:
        return OutputToolGuardResult(
            tool_name=tool_name,
            command=normalized_command,
            allowed=True,
            required_command=required_command,
        )

    return OutputToolGuardResult(
        tool_name=tool_name,
        command=normalized_command,
        allowed=False,
        required_command=required_command,
        errors=[
            f"Tool '{tool_name}' requires command '{required_command.value}' before execution."
        ],
    )
