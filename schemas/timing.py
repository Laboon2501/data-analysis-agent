"""Timing schemas for lightweight runtime instrumentation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel


class TimingRecord(StrictBaseModel):
    """One bounded timing entry for nodes, LLM calls, SQL, or export work."""

    node_name: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    status: str = "completed"
    retry_attempt: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
