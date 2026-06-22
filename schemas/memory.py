"""Memory schemas for retrieved historical analysis cases."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class SimilarCase(StrictBaseModel):
    """Historical case retrieved for planning reference without executing memory logic."""

    case_id: str = Field(default_factory=lambda: str(uuid4()))
    user_question: str
    sql: str | None = None
    chart_type: str | None = None
    insight_summary: str | None = None
    user_correction: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
