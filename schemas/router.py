"""Structured router decision metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from schemas._base import StrictBaseModel

RouterDecisionSource = Literal["rule", "llm", "fallback"]


class RouterDecision(StrictBaseModel):
    """Bounded router decision kept in AgentState for observability."""

    intent: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    needs_datasource: bool = False
    is_followup: bool = False
    referenced_previous_context: bool = False
    source: RouterDecisionSource = "rule"
    command: str | None = None
