"""Schemas for the rule-based direct analysis workflow."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from schemas._base import StrictBaseModel


class DirectQuestionKind(StrEnum):
    """Rule-recognized direct analysis question types."""

    SUMMARY = "summary"
    TIME_TREND = "time_trend"
    TOP_N = "top_n"


class QuestionInterpretation(StrictBaseModel):
    """Structured interpretation produced before planning and SQL drafting."""

    question: str
    kind: DirectQuestionKind
    table_name: str
    metric_field: str
    metric_aggregation: str = "sum"
    time_field: str | None = None
    dimension_field: str | None = None
    top_n: int | None = Field(default=None, ge=1)


class ResultCheck(StrictBaseModel):
    """Structured result quality check before chart and insight generation."""

    is_valid: bool = True
    is_empty: bool = False
    needs_repair: bool = False
    repair_attempts: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
