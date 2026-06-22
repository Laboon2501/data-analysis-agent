"""Dashboard specification schemas for JSON artifact exports."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now
from schemas.chart import ChartType


class DashboardWidgetType(StrEnum):
    """Supported lightweight dashboard widget kinds."""

    METRIC = "metric"
    CHART = "chart"
    TABLE = "table"
    INSIGHT = "insight"
    TEXT = "text"


class DashboardLayout(StrictBaseModel):
    """Grid location for one dashboard widget."""

    x: int = Field(default=0, ge=0)
    y: int = Field(default=0, ge=0)
    w: int = Field(default=4, ge=1)
    h: int = Field(default=3, ge=1)


class DashboardFilter(StrictBaseModel):
    """Filter metadata for future dashboard renderers."""

    filter_id: str = Field(default_factory=lambda: str(uuid4()))
    field: str
    label: str
    filter_type: str = "select"
    values: list[Any] = Field(default_factory=list)


class DashboardWidget(StrictBaseModel):
    """One dashboard widget that references artifacts instead of embedding content."""

    widget_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    widget_type: DashboardWidgetType
    layout: DashboardLayout
    chart_type: ChartType | None = None
    chart_artifact_ref: str | None = None
    query_result_id: str | None = None
    metric_name: str | None = None
    value: Any | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardSpec(StrictBaseModel):
    """Structured dashboard spec saved as a JSON artifact."""

    dashboard_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    source_package_id: str | None = None
    question: str | None = None
    version: str = "1"
    widgets: list[DashboardWidget] = Field(default_factory=list)
    filters: list[DashboardFilter] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class DashboardArtifactMetadata(StrictBaseModel):
    """Artifact metadata for dashboard specs without full widget content."""

    dashboard_id: str
    title: str
    source_analysis_package_id: str | None = None
    widget_count: int = 0
    filter_count: int = 0
    chart_artifact_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
