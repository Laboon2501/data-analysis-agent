"""Event stream schemas for long-running jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class EventType(StrEnum):
    """Allowed event types emitted by workers and graph nodes."""

    NODE_START = "node_start"
    NODE_END = "node_end"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TEXT_DELTA = "text_delta"
    CHART_REF = "chart_ref"
    ARTIFACT_REF = "artifact_ref"
    HUMAN_REQUEST = "human_request"
    USAGE = "usage"
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    LLM_ERROR = "llm_error"
    LLM_FALLBACK = "llm_fallback"
    LLM_JSON_INVALID = "llm_json_invalid"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


class AgentEvent(StrictBaseModel):
    """Single structured event entry for SSE or WebSocket transports."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    session_id: str | None = None
    job_id: str | None = None
    node_name: str | None = None
    tool_name: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
