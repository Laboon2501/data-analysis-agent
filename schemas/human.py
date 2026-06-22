"""Human-in-the-loop request schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class HumanRequestType(StrEnum):
    """Situations that require an explicit user confirmation."""

    FIELD_SEMANTIC_AMBIGUITY = "field_semantic_ambiguity"
    BUSINESS_RULE_CONFIRMATION = "business_rule_confirmation"
    EXPLORATION_PLAN_CONFIRMATION = "exploration_plan_confirmation"
    SQL_RISK_CONFIRMATION = "sql_risk_confirmation"
    EXPORT_OUTLINE_CONFIRMATION = "export_outline_confirmation"
    EXPORT_OUTLINE_REVISION = "export_outline_revision"


class HumanRequest(StrictBaseModel):
    """Structured pause request emitted by graphs before risky or ambiguous work."""

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    request_type: HumanRequestType
    prompt: str
    options: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    created_at: datetime = Field(default_factory=utc_now)
