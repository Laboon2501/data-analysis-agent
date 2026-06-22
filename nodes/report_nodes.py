"""Report outline and export fast-path nodes."""

from __future__ import annotations

from collections.abc import Callable

from guards.output_tool_guard import EXPORT_TOOL_CONFIRM_COMMANDS, check_output_tool_allowed
from persistence.interfaces import ArtifactStore
from schemas.agent_state import AgentCommand, AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.event import AgentEvent, EventType
from schemas.human import HumanRequest, HumanRequestType
from schemas.report import ReportFormat, ReportOutline, ReportResult
from tools.export_tools import (
    export_excel,
    export_report,
    generate_dashboard,
    generate_ppt,
    propose_dashboard_outline,
    propose_excel_export,
    propose_ppt_outline,
    propose_report_outline,
)

CONFIRM_COMMAND_FORMATS: dict[AgentCommand, ReportFormat] = {
    AgentCommand.REPORT_CONFIRM: ReportFormat.REPORT,
    AgentCommand.PPT_CONFIRM: ReportFormat.PPT,
    AgentCommand.EXCEL_CONFIRM: ReportFormat.EXCEL,
    AgentCommand.DASHBOARD_CONFIRM: ReportFormat.DASHBOARD,
}

OUTLINE_PROPOSERS: dict[ReportFormat, Callable] = {
    ReportFormat.REPORT: propose_report_outline,
    ReportFormat.PPT: propose_ppt_outline,
    ReportFormat.EXCEL: propose_excel_export,
    ReportFormat.DASHBOARD: propose_dashboard_outline,
}

EXPORTERS: dict[
    AgentCommand,
    Callable[[ReportOutline, ArtifactStore, AnalysisPackage | None], ReportResult],
] = {
    AgentCommand.REPORT_CONFIRM: export_report,
    AgentCommand.PPT_CONFIRM: generate_ppt,
    AgentCommand.EXCEL_CONFIRM: export_excel,
    AgentCommand.DASHBOARD_CONFIRM: generate_dashboard,
}


class ReportExportPreconditionError(RuntimeError):
    """报告导出前置条件不足时使用的结构化错误。"""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def analysis_package(state: AgentState) -> AgentState:
    """Validate that the graph has package input or a confirmed outline fast-path."""

    if state.analysis_package is None:
        raise ReportExportPreconditionError(
            "export_missing_analysis_package",
            "当前会话没有可复用的分析结果，请先完成一次分析或开放探索。",
            details={"command": state.command.value},
        )
    return state


def generate_outline(
    state: AgentState,
    *,
    default_format: ReportFormat = ReportFormat.REPORT,
) -> AgentState:
    """Generate a deterministic outline unless this is a confirm fast-path."""

    if state.report_outline is not None:
        return state
    if state.analysis_package is None:
        raise ReportExportPreconditionError(
            "export_missing_analysis_package",
            "当前会话没有可复用的分析结果，请先完成一次分析或开放探索。",
            details={"command": state.command.value},
        )

    outline_format = CONFIRM_COMMAND_FORMATS.get(state.command, default_format)
    proposer = OUTLINE_PROPOSERS[outline_format]
    state.report_outline = proposer(state.analysis_package)
    return state


def request_report_confirm(state: AgentState) -> AgentState:
    """Create a structured human confirmation request for an export outline."""

    if _is_confirm_command(state.command):
        state.needs_human = False
        state.human_request = None
        return state
    if state.report_outline is None:
        raise ValueError("ReportOutline is required before requesting confirmation.")

    state.needs_human = True
    state.human_request = HumanRequest(
        request_type=HumanRequestType.EXPORT_OUTLINE_CONFIRMATION,
        prompt="请确认导出大纲，确认后再生成文件。",
        options=[
            f"{state.report_outline.report_format.value}_confirm",
            "revise_outline",
        ],
        context={
            "outline_id": state.report_outline.outline_id,
            "report_format": state.report_outline.report_format.value,
            "title": state.report_outline.title,
        },
    )
    state.events.append(
        AgentEvent(
            event_type=EventType.HUMAN_REQUEST,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="human_confirm",
            message=state.human_request.prompt,
            payload=state.human_request.model_dump(mode="json"),
        )
    )
    return state


def export_file(
    state: AgentState,
    *,
    artifact_store: ArtifactStore,
) -> AgentState:
    """Run the matching placeholder export only for explicit confirm commands."""

    if state.report_outline is None:
        raise ReportExportPreconditionError(
            "export_missing_report_outline",
            "报告生成失败：缺少报告大纲，请重新生成报告大纲或选择导出类型。",
            details={"command": state.command.value},
        )
    tool_name = _tool_name_for_command(state.command)
    guard_result = check_output_tool_allowed(tool_name, state.command)
    if not guard_result.allowed:
        raise PermissionError("; ".join(guard_result.errors))
    if state.analysis_package is None:
        raise ReportExportPreconditionError(
            "export_missing_analysis_package",
            "当前会话没有可复用的分析结果，请先完成一次分析或开放探索。",
            details={"command": state.command.value},
        )
    if not _package_has_exportable_content(state.analysis_package):
        raise ReportExportPreconditionError(
            "export_missing_content",
            "当前探索结果缺少可导出的表格/图表，请先生成分析结果或选择具体分析方向。",
            details={"package_id": state.analysis_package.package_id},
        )

    export_outline = _outline_for_confirm_command(state)
    exporter = EXPORTERS[state.command]
    state.report_result = exporter(export_outline, artifact_store, state.analysis_package)
    state.needs_human = False
    state.events.append(
        AgentEvent(
            event_type=EventType.ARTIFACT_REF,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="export_file",
            tool_name=tool_name,
            message="导出 artifact 已生成。",
            payload=state.report_result.model_dump(mode="json"),
        )
    )
    return state


def return_artifact(state: AgentState) -> AgentState:
    """Attach the export result to the final response without inline file content."""

    if state.report_result is None:
        raise ValueError("ReportResult is required before returning an artifact.")

    format_label = _format_label(state.report_result.report_format)
    state.final_response_text = f"{format_label} 已生成：{state.report_result.artifact_ref}"
    state.events.append(
        AgentEvent(
            event_type=EventType.DONE,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="return_artifact",
            message="报告导出已完成。",
            payload={"artifact_ref": state.report_result.artifact_ref},
        )
    )
    return state


def route_after_analysis_package(state: AgentState) -> str:
    """Only skip outline generation when a confirmed outline already exists."""

    if _is_confirm_command(state.command) and state.report_outline is not None:
        return "export_file"
    return "generate_outline"


def should_export_after_confirmation(state: AgentState) -> str:
    """Route to export only when a confirm command is active."""

    return "export_file" if _is_confirm_command(state.command) else "__end__"


def _is_confirm_command(command: AgentCommand) -> bool:
    """Return whether the command is one of the export fast-path commands."""

    return command in CONFIRM_COMMAND_FORMATS


def _tool_name_for_command(command: AgentCommand) -> str:
    """Map a confirm command to its guarded export tool name."""

    for tool_name, required_command in EXPORT_TOOL_CONFIRM_COMMANDS.items():
        if command is required_command:
            return tool_name
    raise PermissionError(f"Command '{command.value}' is not allowed to export artifacts.")


def _outline_for_confirm_command(state: AgentState) -> ReportOutline:
    """Return the saved outline adapted to the confirmed export format."""

    if state.report_outline is None:
        raise ValueError("ReportOutline is required for confirmation.")
    expected_format = CONFIRM_COMMAND_FORMATS.get(state.command)
    if expected_format is None:
        raise PermissionError(f"Command '{state.command.value}' is not an export confirmation.")
    if state.report_outline.report_format is expected_format:
        return state.report_outline
    return state.report_outline.model_copy(update={"report_format": expected_format}, deep=True)


def _package_has_exportable_content(package: AnalysisPackage) -> bool:
    """判断分析包是否有可导出的轻量内容。"""

    return bool(
        package.sql_result is not None
        or package.chart_spec is not None
        or package.insights
        or package.artifact_refs
    )


def _format_label(report_format: ReportFormat) -> str:
    """Return a Chinese label for one export format."""

    labels = {
        ReportFormat.REPORT: "报告",
        ReportFormat.PPT: "PPT",
        ReportFormat.EXCEL: "Excel",
        ReportFormat.DASHBOARD: "Dashboard",
    }
    return labels.get(report_format, report_format.value)
