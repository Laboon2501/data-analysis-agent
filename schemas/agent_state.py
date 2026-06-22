"""Shared state contract passed between LangGraph nodes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from schemas._base import StrictBaseModel
from schemas.analysis_package import AnalysisPackage
from schemas.analysis_plan import AnalysisPlan
from schemas.chart import ChartSpec
from schemas.context_summary import AgentContextSummary
from schemas.database_profile import DatabaseProfile, ProfileStatus
from schemas.direct_analysis import QuestionInterpretation, ResultCheck
from schemas.errors import AgentError
from schemas.event import AgentEvent
from schemas.human import HumanRequest
from schemas.insight import Insight
from schemas.memory import SimilarCase
from schemas.open_exploration import ExplorationFinding, ExplorationPlan, ExplorationSummary
from schemas.query_result import QueryResult
from schemas.report import ReportOutline, ReportResult
from schemas.router import RouterDecision
from schemas.schema_qa import SchemaQAResult
from schemas.sql import SqlDraft, SqlValidation
from schemas.timing import TimingRecord


class AgentCommand(StrEnum):
    """Command labels used by routers and fast-path export confirmations."""

    NONE = "none"
    PROFILE = "profile"
    ANALYZE = "analyze"
    EXPLORE = "explore"
    REPORT = "report"
    SCHEMA_QA = "schema_qa"
    PPT_CONFIRM = "ppt_confirm"
    REPORT_CONFIRM = "report_confirm"
    EXCEL_CONFIRM = "excel_confirm"
    DASHBOARD_CONFIRM = "dashboard_confirm"


class AgentIntent(StrEnum):
    """Router intent labels for the top-level analysis graph."""

    UNKNOWN = "unknown"
    CONTEXT_MANAGER = "context_manager"
    DIRECT_ANALYSIS = "direct_analysis"
    OPEN_EXPLORATION = "open_exploration"
    REPORT_EXPORT = "report_export"
    SCHEMA_QA = "schema_qa"
    CLARIFICATION = "clarification"


class AgentState(StrictBaseModel):
    """Canonical workflow state shared by all graphs."""

    session_id: str
    job_id: str
    user_message: str
    response_language: str = "zh-CN"
    command: AgentCommand = AgentCommand.NONE
    intent: AgentIntent = AgentIntent.UNKNOWN
    router_decision: RouterDecision | None = None
    context_summary: AgentContextSummary | None = None
    datasource_id: str | None = None
    database_profile: DatabaseProfile | None = None
    profile_status: ProfileStatus = ProfileStatus.MISSING
    similar_cases: list[SimilarCase] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    question_interpretation: QuestionInterpretation | None = None
    analysis_plan: AnalysisPlan | None = None
    exploration_plan: ExplorationPlan | None = None
    sql_draft: SqlDraft | None = None
    sql_validation: SqlValidation | None = None
    sql_result: QueryResult | None = None
    result_check: ResultCheck | None = None
    chart_spec: ChartSpec | None = None
    last_user_question: str | None = None
    last_question_interpretation: QuestionInterpretation | None = None
    last_analysis_plan: AnalysisPlan | None = None
    last_sql_draft: SqlDraft | None = None
    last_sql_result_summary: dict[str, int | float | str | None] | None = None
    last_chart_spec: ChartSpec | None = None
    is_followup_correction: bool = False
    insights: list[Insight] = Field(default_factory=list)
    exploration_findings: list[ExplorationFinding] = Field(default_factory=list)
    exploration_summary: ExplorationSummary | None = None
    schema_qa_result: SchemaQAResult | None = None
    analysis_package: AnalysisPackage | None = None
    report_outline: ReportOutline | None = None
    report_result: ReportResult | None = None
    human_request: HumanRequest | None = None
    needs_human: bool = False
    final_response_text: str | None = None
    retry_count_by_node: dict[str, int] = Field(default_factory=dict)
    error_count: int = Field(default=0, ge=0)
    errors: list[AgentError] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    timing_records: list[TimingRecord] = Field(default_factory=list)
