"""Final analysis package assembled before user response or export."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now
from schemas.analysis_plan import AnalysisPlan
from schemas.chart import ChartSpec
from schemas.insight import Insight
from schemas.query_result import QueryResult


class AnalysisPackage(StrictBaseModel):
    """Clean bundle of plan, result, chart, and insight references."""

    package_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    analysis_plan: AnalysisPlan | None = None
    sql_result: QueryResult | None = None
    chart_spec: ChartSpec | None = None
    insights: list[Insight] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
