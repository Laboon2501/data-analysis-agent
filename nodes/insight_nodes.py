"""Rule-based insight generation nodes."""

from __future__ import annotations

from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from schemas.agent_state import AgentState
from schemas.direct_analysis import DirectQuestionKind
from schemas.event import AgentEvent, EventType
from schemas.insight import Insight


def generate_insight(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Generate an insight using rule defaults or a narrow LLM prompt."""

    if state.question_interpretation is None:
        raise ValueError("QuestionInterpretation is required before insight generation.")
    if state.sql_result is None:
        raise ValueError("QueryResult is required before insight generation.")
    if strategy == "llm":
        try:
            return _generate_insight_with_llm(
                state,
                llm_client=llm_client,
                prompt_loader=prompt_loader,
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="generate_insight",
                prompt_name="insight_writer",
                llm_client=llm_client,
                exc=exc,
            )
            return _generate_insight_with_rules(state)
    return _generate_insight_with_rules(state)


def _generate_insight_with_rules(state: AgentState) -> AgentState:
    """Generate a short deterministic insight from QueryResult."""

    interpretation = state.question_interpretation
    if interpretation is None or state.sql_result is None:
        raise ValueError("QuestionInterpretation and QueryResult are required.")
    if state.sql_result.row_count == 0:
        summary = "查询没有返回结果。"
        evidence = ["row_count=0"]
    elif interpretation.kind is DirectQuestionKind.TIME_TREND:
        summary = f"已完成趋势分析，共返回 {state.sql_result.row_count} 个时间点。"
        evidence = [f"periods={state.sql_result.row_count}"]
    elif interpretation.kind is DirectQuestionKind.TOP_N:
        summary = f"已完成 TopN 分析，共返回 {state.sql_result.row_count} 条排名结果。"
        evidence = [f"ranked_rows={state.sql_result.row_count}"]
    else:
        value = _first_result_value(state.sql_result.rows)
        summary = f"汇总结果为 {value}。"
        evidence = [f"value={value}"]

    state.insights = [
        Insight(
            title="规则分析洞察",
            summary=summary,
            evidence=evidence,
            confidence=0.7,
        )
    ]
    return state


def _generate_insight_with_llm(
    state: AgentState,
    *,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> AgentState:
    """Generate one insight from a narrow JSON LLM response."""

    if state.question_interpretation is None or state.sql_result is None:
        raise ValueError("QuestionInterpretation and QueryResult are required.")
    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="insight_writer",
        prompt_loader=prompt_loader,
        state=state,
        node_name="generate_insight",
        user_payload={
            "question_interpretation": state.question_interpretation.model_dump(mode="json"),
            "query_result": state.sql_result.model_dump(mode="json"),
            "chart_spec": (
                state.chart_spec.model_dump(mode="json") if state.chart_spec is not None else None
            ),
        },
    )
    summary = str(payload["summary"]).strip()
    if not summary:
        raise ValueError("LLM insight summary must not be empty.")
    if _looks_english_user_text(summary):
        state.events.append(
            AgentEvent(
                event_type=EventType.LLM_FALLBACK,
                session_id=state.session_id,
                job_id=state.job_id,
                node_name="generate_insight",
                message="模型返回英文洞察，已回退到中文规则文案。",
                payload={
                    "fallback_reason": "non_chinese_user_text",
                    "switched_to_rule_strategy": True,
                },
            )
        )
        return _generate_insight_with_rules(state)
    state.insights = [
        Insight(
            title=payload.get("title", "模型分析洞察"),
            summary=summary,
            evidence=payload.get("evidence", []),
            confidence=payload.get("confidence"),
        )
    ]
    return state


def _first_result_value(rows: list[dict[str, object]]) -> object:
    """Return the first value from the first result row."""

    if not rows:
        return None
    first_row = rows[0]
    if not first_row:
        return None
    return next(iter(first_row.values()))


def _looks_english_user_text(value: str) -> bool:
    """Detect obvious English-only user-facing LLM text for Chinese fallback."""

    letters = sum(1 for char in value if char.isascii() and char.isalpha())
    cjk = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    return letters >= 12 and cjk == 0
