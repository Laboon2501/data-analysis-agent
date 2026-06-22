"""离线 eval case schema 与回归指标计算。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import Field

from guards.sql_guard import validate_select_only_sql
from schemas._base import StrictBaseModel
from schemas.agent_state import AgentIntent, AgentState
from schemas.chart import ChartType
from schemas.event import AgentEvent, EventType
from schemas.query_result import QueryResult
from schemas.report import ReportFormat

MAX_EVENT_PAYLOAD_CHARS = 2_000
MAX_FINAL_RESPONSE_CHARS = 2_000
REACT_MARKERS: tuple[str, ...] = (
    "Thought:",
    "Action:",
    "Observation:",
    "Final Answer:",
)
LARGE_PAYLOAD_MARKERS: tuple[str, ...] = (
    "<!DOCTYPE html",
    "<html",
    "PK\x03\x04",
)


class EvalCase(StrictBaseModel):
    """单条离线评估用例的结构化契约。"""

    case_id: str
    tags: list[str] = Field(default_factory=list)
    datasource_fixture: str
    previous_user_message: str | None = None
    user_message: str
    expected_intent: AgentIntent
    expected_sql_contains: list[str] = Field(default_factory=list)
    expected_tables: list[str] = Field(default_factory=list)
    expected_metrics: list[str] = Field(default_factory=list)
    expected_chart_type: ChartType | None = None
    expected_artifact_types: list[ReportFormat] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    notes: str | None = None


class EvalCaseResult(StrictBaseModel):
    """单条 eval case 的指标结果。"""

    case_id: str
    passed: bool
    metrics: dict[str, bool | None]
    stats: dict[str, int | float | None] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class EvalSummary(StrictBaseModel):
    """一次 eval run 的汇总结果，可直接序列化为 summary JSON。"""

    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    metric_rates: dict[str, float | None]
    stats: dict[str, int | float | None] = Field(default_factory=dict)
    results: list[EvalCaseResult] = Field(default_factory=list)


def evaluate_case_result(
    case: EvalCase,
    state: AgentState,
    *,
    generated_artifact_types: Iterable[ReportFormat | str] = (),
    sql_strings: Iterable[str] | None = None,
) -> EvalCaseResult:
    """根据最终 AgentState 与 artifact 引用计算单条 case 指标。"""

    active_sql_strings = list(sql_strings or extract_sql_strings(state))
    metrics: dict[str, bool | None] = {
        "intent_accuracy": state.intent is case.expected_intent,
        "sql_table_match": sql_table_match(case, state, active_sql_strings),
        "sql_field_match": sql_field_match(case, state, active_sql_strings),
        "sql_table_field_match": sql_table_field_match(case, state, active_sql_strings),
        "sql_safety": sql_safety_pass(active_sql_strings),
        "result_non_empty_rate": result_non_empty(state),
        "chart_type_match": chart_type_match(case, state),
        "artifact_generation": artifact_generation_pass(case, generated_artifact_types),
        "router_intent_accuracy": (
            state.intent is case.expected_intent if "router" in case.tags else None
        ),
        "no_sql_for_chat": no_sql_for_chat(case, active_sql_strings),
        "no_react_tool_free_call_violation": no_react_tool_free_call_violation(
            case,
            state,
            active_sql_strings,
        ),
        "no_large_payload_in_events_history": no_large_payload_in_events_history(state),
    }
    violations = [
        metric_name for metric_name, metric_value in metrics.items() if metric_value is False
    ]
    stats = collect_eval_stats(state, active_sql_strings)
    details = (
        case_failure_details(case, state, active_sql_strings)
        if violations or _has_llm_events(state) or state.errors
        else {}
    )
    return EvalCaseResult(
        case_id=case.case_id,
        passed=not violations,
        metrics=metrics,
        stats=stats,
        violations=violations,
        details=details,
    )


def summarize_eval_results(results: list[EvalCaseResult]) -> EvalSummary:
    """汇总多条 eval case 的通过率与分项指标通过率。"""

    total_cases = len(results)
    passed_cases = sum(1 for result in results if result.passed)
    metric_names = sorted({metric for result in results for metric in result.metrics})
    metric_rates: dict[str, float | None] = {}
    for metric_name in metric_names:
        scored_values = [
            result.metrics[metric_name]
            for result in results
            if result.metrics.get(metric_name) is not None
        ]
        metric_rates[metric_name] = (
            None
            if not scored_values
            else sum(1 for value in scored_values if value) / len(scored_values)
        )

    stats = summarize_eval_stats(results)
    stats.update(_summary_metric_aliases(metric_rates))
    return EvalSummary(
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=0 if total_cases == 0 else passed_cases / total_cases,
        metric_rates=metric_rates,
        stats=stats,
        results=results,
    )


def collect_eval_stats(
    state: AgentState,
    sql_strings: Iterable[str],
) -> dict[str, int | float | None]:
    """Collect LLM and SQLGuard diagnostics without changing pass/fail semantics."""

    sql_values = list(sql_strings)
    generated_sql_count = len(sql_values)
    sql_guard_block_count = sum(
        1 for sql in sql_values if not validate_select_only_sql(sql, dialect="sqlite").is_allowed
    )
    generated_sql_valid_count = generated_sql_count - sql_guard_block_count
    event_types = [event.event_type for event in state.events]
    return {
        "llm_call_count": event_types.count(EventType.LLM_START),
        "llm_error_count": event_types.count(EventType.LLM_ERROR),
        "llm_fallback_count": event_types.count(EventType.LLM_FALLBACK),
        "llm_json_invalid_count": event_types.count(EventType.LLM_JSON_INVALID),
        "sql_guard_block_count": sql_guard_block_count,
        "generated_sql_valid_rate": (
            None if generated_sql_count == 0 else generated_sql_valid_count / generated_sql_count
        ),
        "generated_sql_count": generated_sql_count,
        "generated_sql_valid_count": generated_sql_valid_count,
    }


def summarize_eval_stats(results: list[EvalCaseResult]) -> dict[str, int | float | None]:
    """Aggregate diagnostic stats across eval case results."""

    count_keys = (
        "llm_call_count",
        "llm_error_count",
        "llm_fallback_count",
        "llm_json_invalid_count",
        "sql_guard_block_count",
        "generated_sql_count",
        "generated_sql_valid_count",
    )
    stats: dict[str, int | float | None] = {}
    for key in count_keys:
        stats[key] = int(sum((result.stats.get(key) or 0) for result in results))

    generated_sql_count = stats["generated_sql_count"] or 0
    generated_sql_valid_count = stats["generated_sql_valid_count"] or 0
    llm_call_count = stats["llm_call_count"] or 0
    llm_fallback_count = stats["llm_fallback_count"] or 0
    llm_json_invalid_count = stats["llm_json_invalid_count"] or 0
    stats["generated_sql_valid_rate"] = (
        None
        if generated_sql_count == 0
        else float(generated_sql_valid_count) / float(generated_sql_count)
    )
    stats["fallback_rate"] = (
        0.0 if llm_call_count == 0 else float(llm_fallback_count) / float(llm_call_count)
    )
    stats["json_invalid_rate"] = (
        0.0 if llm_call_count == 0 else float(llm_json_invalid_count) / float(llm_call_count)
    )
    return stats


def _summary_metric_aliases(
    metric_rates: dict[str, float | None],
) -> dict[str, int | float | None]:
    """Expose product-facing summary metric names without changing case metrics."""

    return {
        "intent_accuracy": metric_rates.get("intent_accuracy"),
        "router_accuracy": metric_rates.get("router_intent_accuracy"),
        "sql_table_match_rate": metric_rates.get("sql_table_match"),
        "sql_field_match_rate": metric_rates.get("sql_field_match"),
        "artifact_pass_rate": metric_rates.get("artifact_generation"),
        "no_sql_for_chat_pass_rate": metric_rates.get("no_sql_for_chat"),
    }


def sql_table_field_match(
    case: EvalCase,
    state: AgentState,
    sql_strings: Iterable[str],
) -> bool | None:
    """检查 SQL 或 DatabaseProfile 是否覆盖期望表与字段。"""

    sql_values = list(sql_strings)
    has_sql_expectation = bool(
        case.expected_sql_contains or case.expected_tables or case.expected_metrics
    )
    if sql_values:
        sql_text = "\n".join(sql_values).lower()
        return (
            _contains_all(sql_text, case.expected_sql_contains)
            and _contains_all(sql_text, case.expected_tables)
            and _contains_metric_columns(sql_text, case.expected_metrics)
        )

    if state.database_profile is not None and has_sql_expectation:
        profile_tables = {table.name for table in state.database_profile.tables}
        profile_metrics = set(state.database_profile.candidate_metrics)
        return set(case.expected_tables).issubset(profile_tables) and set(
            case.expected_metrics
        ).issubset(profile_metrics)

    return None


def sql_table_match(
    case: EvalCase,
    state: AgentState,
    sql_strings: Iterable[str],
) -> bool | None:
    """检查 SQL 或 DatabaseProfile 是否覆盖期望表。"""

    if not case.expected_tables:
        return None
    sql_values = list(sql_strings)
    if sql_values:
        sql_text = "\n".join(sql_values).lower()
        return _contains_all(sql_text, case.expected_tables)
    if state.database_profile is not None:
        profile_tables = {table.name for table in state.database_profile.tables}
        return set(case.expected_tables).issubset(profile_tables)
    return None


def sql_field_match(
    case: EvalCase,
    state: AgentState,
    sql_strings: Iterable[str],
) -> bool | None:
    """检查 SQL 或 DatabaseProfile 是否覆盖期望指标字段。"""

    if not case.expected_metrics:
        return None
    sql_values = list(sql_strings)
    if sql_values:
        sql_text = "\n".join(sql_values).lower()
        return _contains_metric_columns(sql_text, case.expected_metrics)
    if state.database_profile is not None:
        profile_metrics = set(state.database_profile.candidate_metrics)
        return set(case.expected_metrics).issubset(profile_metrics)
    return None


def sql_safety_pass(sql_strings: Iterable[str]) -> bool | None:
    """用 SQLGuard 检查所有 eval SQL 是否只读安全。"""

    sql_values = list(sql_strings)
    if not sql_values:
        return None
    return all(validate_select_only_sql(sql, dialect="sqlite").is_allowed for sql in sql_values)


def no_sql_for_chat(case: EvalCase, sql_strings: Iterable[str]) -> bool | None:
    """聊天/帮助/无效请求不应生成 SQL。"""

    if case.expected_intent not in {AgentIntent.CLARIFICATION, AgentIntent.SCHEMA_QA}:
        return None
    return not list(sql_strings)


def result_non_empty(state: AgentState) -> bool | None:
    """检查分析结果是否至少包含一组非空查询结果。"""

    query_results = extract_query_results(state)
    if not query_results:
        return None
    return any(query_result.row_count > 0 for query_result in query_results)


def chart_type_match(case: EvalCase, state: AgentState) -> bool | None:
    """检查图表类型是否符合 case 期望。"""

    if case.expected_chart_type is None:
        return None
    chart_spec = state.chart_spec
    if chart_spec is None and state.analysis_package is not None:
        chart_spec = state.analysis_package.chart_spec
    if chart_spec is None and state.exploration_findings:
        chart_spec = state.exploration_findings[0].chart_spec
    return chart_spec is not None and chart_spec.chart_type is case.expected_chart_type


def artifact_generation_pass(
    case: EvalCase,
    generated_artifact_types: Iterable[ReportFormat | str],
) -> bool | None:
    """检查报告导出 case 是否生成了期望 artifact 类型。"""

    if not case.expected_artifact_types:
        return None
    actual_types = {
        artifact_type.value if isinstance(artifact_type, ReportFormat) else str(artifact_type)
        for artifact_type in generated_artifact_types
    }
    expected_types = {artifact_type.value for artifact_type in case.expected_artifact_types}
    return expected_types.issubset(actual_types)


def no_react_tool_free_call_violation(
    case: EvalCase,
    state: AgentState,
    sql_strings: Iterable[str],
) -> bool:
    """检查输出中没有隐藏 ReAct 痕迹或 case 明确禁止的文本。"""

    safe_text = _safe_state_text(state, sql_strings)
    blocked_markers = (*REACT_MARKERS, *case.must_not_contain)
    return not any(marker and marker in safe_text for marker in blocked_markers)


def no_large_payload_in_events_history(state: AgentState) -> bool:
    """检查事件和最终回复没有携带图表 HTML 或导出文件正文。"""

    if state.final_response_text and len(state.final_response_text) > MAX_FINAL_RESPONSE_CHARS:
        return False
    for event in state.events:
        event_payload = _event_payload_text(event)
        if len(event_payload) > MAX_EVENT_PAYLOAD_CHARS:
            return False
        if any(marker in event_payload for marker in LARGE_PAYLOAD_MARKERS):
            return False
    return True


def extract_sql_strings(state: AgentState) -> list[str]:
    """从 AgentState 中收集用于 eval 的 SQL 文本，不读取 artifact 内容。"""

    sql_values: list[str] = []
    if state.sql_draft is not None:
        sql_values.append(state.sql_draft.query)
    for query_result in extract_query_results(state):
        sql_values.append(query_result.sql)
    for finding in state.exploration_findings:
        if finding.sql:
            sql_values.append(finding.sql)
    return _deduplicate(sql_values)


def case_failure_details(
    case: EvalCase,
    state: AgentState,
    sql_strings: Iterable[str],
) -> dict[str, Any]:
    """Return bounded debug details for failed real/fake LLM eval cases."""

    generated_sql = list(sql_strings)
    llm_events = [
        {
            "event_type": event.event_type.value,
            "node_name": event.node_name,
            "message": event.message,
            "payload": event.payload,
        }
        for event in state.events
        if event.event_type
        in {
            EventType.LLM_START,
            EventType.LLM_END,
            EventType.LLM_ERROR,
            EventType.LLM_FALLBACK,
            EventType.LLM_JSON_INVALID,
        }
    ]
    return {
        "expected": {
            "intent": case.expected_intent.value,
            "tables": case.expected_tables,
            "metrics": case.expected_metrics,
            "sql_contains": case.expected_sql_contains,
            "artifact_types": [artifact.value for artifact in case.expected_artifact_types],
            "must_not_contain": case.must_not_contain,
        },
        "actual_intent": state.intent.value,
        "generated_sql": generated_sql,
        "sql_validation": (
            state.sql_validation.model_dump(mode="json")
            if state.sql_validation is not None
            else None
        ),
        "llm_events": llm_events,
        "fallback_reason": [
            event.payload.get("fallback_reason") or event.payload.get("reason")
            for event in state.events
            if event.event_type is EventType.LLM_FALLBACK
        ],
        "errors": [error.model_dump(mode="json") for error in state.errors],
    }


def _has_llm_events(state: AgentState) -> bool:
    """判断 state 中是否包含 LLM 观测事件。"""

    return any(
        event.event_type
        in {
            EventType.LLM_START,
            EventType.LLM_END,
            EventType.LLM_ERROR,
            EventType.LLM_FALLBACK,
            EventType.LLM_JSON_INVALID,
        }
        for event in state.events
    )


def extract_query_results(state: AgentState) -> list[QueryResult]:
    """从直接分析、开放探索和导出输入中提取 QueryResult。"""

    query_results: list[QueryResult] = []
    if state.sql_result is not None:
        query_results.append(state.sql_result)
    if state.analysis_package is not None and state.analysis_package.sql_result is not None:
        query_results.append(state.analysis_package.sql_result)
    query_results.extend(
        finding.sql_result
        for finding in state.exploration_findings
        if finding.sql_result is not None
    )
    return query_results


def _contains_all(text: str, expected_tokens: Iterable[str]) -> bool:
    return all(token.lower() in text for token in expected_tokens)


def _contains_metric_columns(text: str, expected_metrics: Iterable[str]) -> bool:
    for metric in expected_metrics:
        table_or_column = metric.lower().split(".")
        column_name = table_or_column[-1]
        if column_name not in text:
            return False
    return True


def _safe_state_text(state: AgentState, sql_strings: Iterable[str]) -> str:
    payload = {
        "final_response_text": state.final_response_text,
        "events": [event.model_dump(mode="json") for event in state.events],
        "sql": list(sql_strings),
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _event_payload_text(event: AgentEvent) -> str:
    event_payload: dict[str, Any] = {
        "event_type": event.event_type.value,
        "node_name": event.node_name,
        "tool_name": event.tool_name,
        "message": event.message,
        "payload": event.payload,
    }
    return json.dumps(event_payload, sort_keys=True, default=str)


def _deduplicate(values: Iterable[str]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            unique_values.append(value)
            seen.add(value)
    return unique_values
