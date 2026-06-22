"""Schemas for the rule-based open exploration workflow."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now
from schemas.chart import ChartSpec
from schemas.direct_analysis import DirectQuestionKind
from schemas.insight import Insight
from schemas.query_result import QueryResult


class ExplorationTopic(StrictBaseModel):
    """Candidate analysis topic generated from a DatabaseProfile."""

    topic_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    question: str
    kind: DirectQuestionKind
    metric_field: str
    time_field: str | None = None
    dimension_field: str | None = None
    top_n: int | None = Field(default=None, ge=1)
    priority_score: float = Field(default=0, ge=0)
    rationale: str | None = None


class ExplorationPlan(StrictBaseModel):
    """Ranked exploration plan with selected topics."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    topics: list[ExplorationTopic] = Field(default_factory=list)
    ranked_topic_ids: list[str] = Field(default_factory=list)
    selected_topic_ids: list[str] = Field(default_factory=list)
    top_n: int = Field(default=3, ge=1)
    requires_human_confirmation: bool = False


class ExplorationFinding(StrictBaseModel):
    """Result of running one exploration topic through rule-based analysis."""

    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    topic: ExplorationTopic
    title: str | None = None
    question: str | None = None
    metric_name: str | None = None
    dimension_name: str | None = None
    sql: str | None = None
    sql_result: QueryResult | None = None
    result_summary: str | None = None
    business_interpretation: str | None = None
    chart_spec: ChartSpec | None = None
    chart_type: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    status: str = "completed"
    errors: list[str] = Field(default_factory=list)


class ExplorationSummary(StrictBaseModel):
    """Summary of exploration findings."""

    summary_id: str = Field(default_factory=lambda: str(uuid4()))
    findings: list[ExplorationFinding] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    summary: str
    created_at: datetime = Field(default_factory=utc_now)
