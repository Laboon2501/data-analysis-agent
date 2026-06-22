"""Report and export outline schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel


class ReportFormat(StrEnum):
    """Supported export targets that require human confirmation."""

    REPORT = "report"
    PPT = "ppt"
    EXCEL = "excel"
    DASHBOARD = "dashboard"


class ReportOutlineSection(StrictBaseModel):
    """Single section in an export outline."""

    title: str
    points: list[str] = Field(default_factory=list)


class ReportOutline(StrictBaseModel):
    """Outline or preview that must be confirmed before export."""

    outline_id: str = Field(default_factory=lambda: str(uuid4()))
    report_format: ReportFormat
    title: str
    sections: list[ReportOutlineSection] = Field(default_factory=list)
    source_package_id: str | None = None
    requires_confirmation: bool = True


class ArtifactRef(StrictBaseModel):
    """Opaque artifact reference returned by export placeholder tools."""

    artifact_ref: str
    artifact_type: ReportFormat
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportResult(StrictBaseModel):
    """Export result containing only an artifact reference."""

    report_id: str = Field(default_factory=lambda: str(uuid4()))
    report_format: ReportFormat
    artifact_ref: str
    status: str
    artifact: ArtifactRef | None = None
