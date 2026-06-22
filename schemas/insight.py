"""Insight schemas generated from checked query results and charts."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel


class InsightSeverity(StrEnum):
    """Importance label for an insight."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Insight(StrictBaseModel):
    """Single evidence-backed analytical insight."""

    insight_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    severity: InsightSeverity = InsightSeverity.INFO
    confidence: float | None = Field(default=None, ge=0, le=1)
