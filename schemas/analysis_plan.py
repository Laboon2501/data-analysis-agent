"""Analysis planning schemas shared by direct and exploratory workflows."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel


class AnalysisMode(StrEnum):
    """Supported high-level analysis workflow modes."""

    DIRECT = "direct"
    OPEN_EXPLORATION = "open_exploration"
    REPORT_EXPORT = "report_export"


class AnalysisStep(StrictBaseModel):
    """Single planned step with explicit inputs, outputs, and tool category scope."""

    step_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    objective: str
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    tool_categories: list[str] = Field(default_factory=list)


class AnalysisPlan(StrictBaseModel):
    """Structured plan created before SQL drafting or exploratory analysis."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    mode: AnalysisMode
    question: str
    steps: list[AnalysisStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool = False
