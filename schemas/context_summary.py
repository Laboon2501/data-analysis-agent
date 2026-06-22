"""Compact handoff memory for routing and follow-up context."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class AgentContextSummary(StrictBaseModel):
    """结构化会话摘要，只保存可复用上下文，不保存正文或密钥。"""

    session_id: str
    current_datasource_id: str | None = None
    datasource_profile_summary: str | None = None
    schema_hash: str | None = None
    known_tables: list[str] = Field(default_factory=list)
    known_fields: list[str] = Field(default_factory=list)
    semantic_fields: dict[str, list[str]] = Field(default_factory=dict)
    candidate_metrics: list[str] = Field(default_factory=list)
    candidate_dimensions: list[str] = Field(default_factory=list)
    last_user_intent: str | None = None
    last_user_question: str | None = None
    last_question_interpretation: dict[str, Any] | None = None
    last_analysis_plan_summary: dict[str, Any] | None = None
    last_sql_summary: dict[str, Any] | None = None
    last_result_summary: dict[str, Any] | None = None
    last_open_exploration_summary: dict[str, Any] | None = None
    latest_analysis_package_id: str | None = None
    latest_report_outline_id: str | None = None
    latest_artifact_refs: list[str] = Field(default_factory=list)
    pending_human_request: dict[str, Any] | None = None
    user_corrections: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
