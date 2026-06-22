"""Nodes for controlled schema QA and data inspection answers."""

from __future__ import annotations

from typing import Any

from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.database_profile import DatabaseProfile, FieldProfile, TableProfile
from schemas.schema_qa import SchemaFieldSummary, SchemaQAResult, SchemaTableSummary

MAX_SAMPLE_VALUES = 3
MAX_SAMPLE_TEXT = 60


def answer_schema_question(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Answer schema/data-inspection questions from DatabaseProfile only."""

    if state.database_profile is None:
        raise ValueError("Schema QA requires a database profile.")

    result = build_schema_qa_result(state)
    if strategy == "llm":
        try:
            result = _apply_llm_answer(
                state,
                result,
                llm_client=llm_client,
                prompt_loader=prompt_loader,
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="schema_qa",
                prompt_name="schema_qa",
                llm_client=llm_client,
                exc=exc,
            )

    state.command = AgentCommand.SCHEMA_QA
    state.intent = AgentIntent.SCHEMA_QA
    state.schema_qa_result = result
    state.final_response_text = result.answer
    return state


def build_schema_qa_result(state: AgentState) -> SchemaQAResult:
    """Build a bounded Chinese schema QA result from the current profile."""

    profile = state.database_profile
    if profile is None:
        raise ValueError("Schema QA requires a database profile.")

    tables = [_table_summary(table) for table in profile.tables]
    metrics = list(profile.candidate_metrics or profile.metric_fields)
    dimensions = list(profile.candidate_dimensions or profile.dimension_fields)
    suggestions = _analysis_suggestions(profile)
    answer = _rule_answer(
        question=state.user_message,
        profile=profile,
        tables=tables,
        metrics=metrics,
        dimensions=dimensions,
        suggestions=suggestions,
    )
    return SchemaQAResult(
        question=state.user_message,
        datasource_id=profile.datasource_id,
        answer=answer,
        tables=tables,
        candidate_metrics=metrics,
        candidate_dimensions=dimensions,
        analysis_suggestions=suggestions,
    )


def _apply_llm_answer(
    state: AgentState,
    result: SchemaQAResult,
    *,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> SchemaQAResult:
    """Let an LLM polish the answer using only the bounded schema summary."""

    known_fields = _known_fields(result)
    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="schema_qa",
        prompt_loader=prompt_loader,
        state=state,
        node_name="schema_qa",
        user_payload={
            "task": "schema_qa",
            "user_message": state.user_message,
            "schema_summary": result.model_dump(mode="json", exclude={"answer"}),
            "agent_context_summary": (
                state.context_summary.model_dump(mode="json")
                if state.context_summary is not None
                else None
            ),
            "allowed_fields": sorted(known_fields),
            "language": state.response_language,
        },
    )
    answer = str(payload.get("answer") or "").strip()
    referenced_fields = {
        str(field).strip() for field in payload.get("referenced_fields", []) if str(field).strip()
    }
    if not answer:
        raise ValueError("schema_qa LLM response did not include answer.")
    if referenced_fields and not referenced_fields.issubset(known_fields):
        unknown_fields = sorted(referenced_fields - known_fields)
        raise ValueError(f"schema_qa LLM referenced unknown fields: {unknown_fields}")
    return result.model_copy(update={"answer": answer})


def _table_summary(table: TableProfile) -> SchemaTableSummary:
    """Convert one profiled table to bounded field summaries."""

    return SchemaTableSummary(
        table_name=table.name,
        row_count=table.row_count,
        role=table.role,
        fields=[_field_summary(table.name, field) for field in table.columns],
    )


def _field_summary(table_name: str, field: FieldProfile) -> SchemaFieldSummary:
    """Convert one profiled field without storing large samples."""

    return SchemaFieldSummary(
        table_name=table_name,
        field_name=field.name,
        qualified_name=f"{table_name}.{field.name}",
        data_type=field.data_type,
        semantic_type=field.semantic_type,
        sample_values=[
            _safe_sample_value(value) for value in field.sample_values[:MAX_SAMPLE_VALUES]
        ],
        description=field.description,
        is_metric_candidate=field.is_metric_candidate,
        is_dimension_candidate=field.is_dimension_candidate,
    )


def _rule_answer(
    *,
    question: str,
    profile: DatabaseProfile,
    tables: list[SchemaTableSummary],
    metrics: list[str],
    dimensions: list[str],
    suggestions: list[str],
) -> str:
    """Generate a user-facing Chinese answer without LLM dependency."""

    _ = question
    parts = [
        f"当前数据源 {profile.datasource_id} 已识别 {len(tables)} 张表。",
    ]
    for table in tables:
        field_text = "、".join(f"{field.field_name}（{field.data_type}）" for field in table.fields)
        samples = _sample_text(table)
        row_text = f"，约 {table.row_count} 行" if table.row_count is not None else ""
        parts.append(f"- {table.table_name}{row_text}：{field_text}。{samples}")
    if metrics:
        parts.append(f"候选指标字段：{'、'.join(metrics)}。")
    if dimensions:
        parts.append(f"候选维度字段：{'、'.join(dimensions)}。")
    if suggestions:
        parts.append(f"可以优先尝试：{'；'.join(suggestions)}。")
    return "\n".join(parts)


def _sample_text(table: SchemaTableSummary) -> str:
    """Return a compact sample-value sentence for one table."""

    sample_fragments = []
    for field in table.fields:
        if field.sample_values:
            sample_fragments.append(f"{field.field_name} 示例 {field.sample_values[:2]}")
        if len(sample_fragments) >= 3:
            break
    if not sample_fragments:
        return "暂无样例值摘要。"
    return "样例摘要：" + "；".join(sample_fragments) + "。"


def _analysis_suggestions(profile: DatabaseProfile) -> list[str]:
    """Suggest safe next analysis directions from profiled fields."""

    suggestions: list[str] = []
    if profile.time_fields and (profile.candidate_metrics or profile.metric_fields):
        suggestions.append("按时间查看核心指标趋势")
    if profile.candidate_dimensions and (profile.candidate_metrics or profile.metric_fields):
        suggestions.append("按维度对比指标表现")
    if profile.candidate_dimensions:
        suggestions.append("查看 TopN 排名或分布")
    return suggestions[:4]


def _known_fields(result: SchemaQAResult) -> set[str]:
    """Return field names the LLM is allowed to reference."""

    fields: set[str] = set()
    for table in result.tables:
        fields.add(table.table_name)
        for field in table.fields:
            fields.add(field.field_name)
            fields.add(field.qualified_name)
    fields.update(result.candidate_metrics)
    fields.update(result.candidate_dimensions)
    return fields


def _safe_sample_value(value: Any) -> Any:
    """Bound sample values so file contents cannot leak into events/history."""

    if value is None or isinstance(value, int | float | bool):
        return value
    text = str(value)
    if len(text) <= MAX_SAMPLE_TEXT:
        return text
    return f"{text[:MAX_SAMPLE_TEXT]}..."
