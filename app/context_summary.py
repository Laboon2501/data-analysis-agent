"""Rule-first compaction of AgentState into safe session context."""

from __future__ import annotations

import re
from typing import Any

from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import LLM_FALLBACK_EXCEPTIONS, NodeStrategy, call_llm_for_json
from schemas._base import utc_now
from schemas.agent_state import AgentState
from schemas.context_summary import AgentContextSummary
from schemas.database_profile import DatabaseProfile
from schemas.report import ArtifactRef

MAX_ITEMS = 80
MAX_TEXT = 240
SECRET_PATTERN = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*\S+|bearer\s+[A-Za-z0-9._-]{8,})"
)


def compact_context_summary(
    state: AgentState,
    *,
    previous: AgentContextSummary | None = None,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentContextSummary:
    """把最新工作流状态压缩成可持久化、无正文泄漏的会话摘要。"""

    if strategy == "llm":
        try:
            payload = call_llm_for_json(
                llm_client=llm_client,
                prompt_name="context_compactor",
                prompt_loader=prompt_loader,
                state=state,
                node_name="context_compactor",
                user_payload={
                    "task": "context_compactor",
                    "previous_summary": _dump_summary(previous),
                    "rule_summary": _dump_summary(_compact_with_rules(state, previous=previous)),
                },
            )
            return AgentContextSummary.model_validate(_redact_value(payload))
        except LLM_FALLBACK_EXCEPTIONS:
            return _compact_with_rules(state, previous=previous)
    return _compact_with_rules(state, previous=previous)


def _compact_with_rules(
    state: AgentState,
    *,
    previous: AgentContextSummary | None,
) -> AgentContextSummary:
    profile = state.database_profile
    known_tables = _known_tables(profile) or (previous.known_tables if previous else [])
    known_fields = _known_fields(profile) or (previous.known_fields if previous else [])
    semantic_fields = _semantic_fields(profile) or (previous.semantic_fields if previous else {})
    latest_refs = _merge_refs(
        previous.latest_artifact_refs if previous else [],
        _artifact_refs_from_state(state),
    )
    summary = AgentContextSummary(
        session_id=state.session_id,
        current_datasource_id=state.datasource_id
        or (profile.datasource_id if profile else None)
        or (previous.current_datasource_id if previous else None),
        datasource_profile_summary=_profile_summary(profile)
        or (previous.datasource_profile_summary if previous else None),
        schema_hash=(
            profile.schema_hash if profile else previous.schema_hash if previous else None
        ),
        known_tables=known_tables,
        known_fields=known_fields,
        semantic_fields=semantic_fields,
        candidate_metrics=_bounded_list(
            profile.candidate_metrics if profile else previous.candidate_metrics if previous else []
        ),
        candidate_dimensions=_bounded_list(
            profile.candidate_dimensions
            if profile
            else previous.candidate_dimensions
            if previous
            else []
        ),
        last_user_intent=(
            state.intent.value if state.intent else previous.last_user_intent if previous else None
        ),
        last_user_question=_redact_text(state.user_message)
        if state.user_message
        else previous.last_user_question
        if previous
        else None,
        last_question_interpretation=_model_summary(state.question_interpretation)
        or (previous.last_question_interpretation if previous else None),
        last_analysis_plan_summary=_analysis_plan_summary(state)
        or (previous.last_analysis_plan_summary if previous else None),
        last_sql_summary=_sql_summary(state) or (previous.last_sql_summary if previous else None),
        last_result_summary=_result_summary(state)
        or (previous.last_result_summary if previous else None),
        last_open_exploration_summary=_open_exploration_summary(state)
        or (previous.last_open_exploration_summary if previous else None),
        latest_analysis_package_id=_analysis_package_id(state)
        or (previous.latest_analysis_package_id if previous else None),
        latest_report_outline_id=_report_outline_id(state)
        or (previous.latest_report_outline_id if previous else None),
        latest_artifact_refs=latest_refs,
        pending_human_request=_human_request_summary(state)
        or (previous.pending_human_request if previous else None),
        user_corrections=_corrections(state, previous),
        unresolved_questions=_unresolved_questions(state, previous),
        updated_at=utc_now(),
    )
    return AgentContextSummary.model_validate(_redact_value(summary.model_dump()))


def _dump_summary(summary: AgentContextSummary | None) -> dict[str, Any] | None:
    return None if summary is None else summary.model_dump(mode="json")


def _known_tables(profile: DatabaseProfile | None) -> list[str]:
    if profile is None:
        return []
    return _bounded_list(table.name for table in profile.tables)


def _known_fields(profile: DatabaseProfile | None) -> list[str]:
    if profile is None:
        return []
    fields: list[str] = []
    for table in profile.tables:
        fields.extend(f"{table.name}.{column.name}" for column in table.columns)
    return _bounded_list(fields)


def _semantic_fields(profile: DatabaseProfile | None) -> dict[str, list[str]]:
    if profile is None:
        return {}
    semantic: dict[str, list[str]] = {}
    for table in profile.tables:
        for field in table.columns:
            key = str(field.semantic_type.value if field.semantic_type else "unknown")
            semantic.setdefault(key, []).append(f"{table.name}.{field.name}")
    return {key: _bounded_list(values) for key, values in semantic.items() if values}


def _profile_summary(profile: DatabaseProfile | None) -> str | None:
    if profile is None:
        return None
    field_count = sum(len(table.columns) for table in profile.tables)
    return _redact_text(
        f"{profile.datasource_id}: {len(profile.tables)} 张表，{field_count} 个字段。"
    )


def _model_summary(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
    elif isinstance(value, dict):
        dumped = value
    else:
        return None
    return _bounded_dict(dumped)


def _analysis_plan_summary(state: AgentState) -> dict[str, Any] | None:
    if state.analysis_plan is None:
        return None
    return _bounded_dict(
        {
            "mode": state.analysis_plan.mode.value,
            "question": state.analysis_plan.question,
            "steps": [step.name for step in state.analysis_plan.steps],
            "assumptions": state.analysis_plan.assumptions[:5],
        }
    )


def _sql_summary(state: AgentState) -> dict[str, Any] | None:
    if state.sql_draft is None:
        return None
    validation = state.sql_validation
    return _bounded_dict(
        {
            "sql": state.sql_draft.query,
            "rationale": state.sql_draft.rationale,
            "validated": validation.is_valid if validation else None,
            "errors": validation.errors[:5] if validation else [],
        }
    )


def _result_summary(state: AgentState) -> dict[str, Any] | None:
    if state.sql_result is None:
        return state.last_sql_result_summary
    return _bounded_dict(
        {
            "row_count": state.sql_result.row_count,
            "columns": [column.name for column in state.sql_result.columns],
        }
    )


def _open_exploration_summary(state: AgentState) -> dict[str, Any] | None:
    if state.exploration_summary is None and not state.exploration_findings:
        return None
    return _bounded_dict(
        {
            "summary": state.exploration_summary.summary if state.exploration_summary else None,
            "topics": [finding.topic.title for finding in state.exploration_findings[:5]],
            "findings": [
                finding.business_interpretation or finding.result_summary or finding.title
                for finding in state.exploration_findings[:5]
            ],
        }
    )


def _analysis_package_id(state: AgentState) -> str | None:
    package = state.analysis_package
    return None if package is None else _redact_text(package.package_id)


def _report_outline_id(state: AgentState) -> str | None:
    outline = state.report_outline
    return None if outline is None else _redact_text(outline.outline_id)


def _artifact_refs_from_state(state: AgentState) -> list[str]:
    refs: list[str] = []
    for value in (state.chart_spec, state.analysis_package, state.report_result):
        if hasattr(value, "model_dump"):
            refs.extend(_refs_from_value(value.model_dump(mode="json")))
    return _merge_refs([], refs)


def _refs_from_value(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"artifact_ref", "chart_artifact_ref"} and isinstance(item, str):
                refs.append(_normalize_ref(item))
            elif key in {"artifact_refs", "chart_artifact_refs"} and isinstance(item, list):
                refs.extend(_normalize_ref(str(ref)) for ref in item)
            else:
                refs.extend(_refs_from_value(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_refs_from_value(item))
    return refs


def _human_request_summary(state: AgentState) -> dict[str, Any] | None:
    if state.human_request is None:
        return None
    return _bounded_dict(
        {
            "request_id": state.human_request.request_id,
            "request_type": state.human_request.request_type.value,
            "prompt": state.human_request.prompt,
            "options": state.human_request.options,
        }
    )


def _corrections(
    state: AgentState,
    previous: AgentContextSummary | None,
) -> list[str]:
    values = list(previous.user_corrections if previous else [])
    if state.is_followup_correction and state.user_message:
        values.append(_redact_text(state.user_message))
    return _bounded_list(values, max_items=10)


def _unresolved_questions(
    state: AgentState,
    previous: AgentContextSummary | None,
) -> list[str]:
    values = list(previous.unresolved_questions if previous else [])
    if state.human_request is not None:
        values.append(_redact_text(state.human_request.prompt))
    if state.error_count and state.errors:
        values.append(_redact_text(state.errors[-1].message))
    return _bounded_list(values, max_items=10)


def _bounded_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _redact_value(item) for key, item in value.items() if item not in (None, [], {})
    }


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {
            str(key): _redact_value(item)
            for key, item in list(value.items())[:MAX_ITEMS]
            if not _sensitive_key(str(key))
        }
    return value


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = SECRET_PATTERN.sub("[secret]", str(value))
    return clean if len(clean) <= MAX_TEXT else f"{clean[:MAX_TEXT]}..."


def _sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return any(token in lowered for token in ("api_key", "apikey", "secret", "password", "token"))


def _bounded_list(values: Any, *, max_items: int = MAX_ITEMS) -> list[str]:
    if values is None:
        return []
    result: list[str] = []
    for value in values:
        text = _redact_text(str(value))
        if text and text not in result:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def _merge_refs(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *incoming]:
        normalized = _normalize_ref(value)
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged


def _normalize_ref(value: str | ArtifactRef) -> str:
    if isinstance(value, ArtifactRef):
        value = value.ref
    raw = str(value or "").strip()
    if not raw:
        return ""
    artifact_id = raw.split(":")[-1]
    return f"artifact:{artifact_id}"
