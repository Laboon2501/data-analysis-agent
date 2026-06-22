"""Structured error contracts shared by guards, nodes, and graphs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class ErrorSeverity(StrEnum):
    """Severity levels for workflow errors."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AgentError(StrictBaseModel):
    """Serializable error record kept in state or emitted through events."""

    error_id: str = Field(default_factory=lambda: str(uuid4()))
    code: str
    message: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    node_name: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
