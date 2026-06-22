"""Chart specification schemas that reference artifacts instead of inline HTML."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel


class ChartType(StrEnum):
    """Supported chart families for future chart generation nodes."""

    NONE = "none"
    TABLE = "table"
    LINE = "line"
    BAR = "bar"
    SCATTER = "scatter"
    PIE = "pie"
    AREA = "area"
    HEATMAP = "heatmap"


class ChartSpec(StrictBaseModel):
    """Serializable chart intent and artifact reference."""

    chart_id: str = Field(default_factory=lambda: str(uuid4()))
    chart_type: ChartType = ChartType.NONE
    title: str | None = None
    x: str | None = None
    y: str | None = None
    series: str | None = None
    encoding: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str | None = None
    rationale: str | None = None
