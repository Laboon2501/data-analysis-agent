"""Result checking and bounded SQL repair nodes."""

from __future__ import annotations

from datasource.base import DataSource
from schemas.agent_state import AgentState
from schemas.direct_analysis import ResultCheck
from schemas.event import AgentEvent, EventType
from schemas.human import HumanRequest, HumanRequestType

SQL_REPAIR_NODE = "repair_sql_if_needed"


def check_result(state: AgentState) -> AgentState:
    """Check query result shape before chart and insight generation."""

    errors: list[str] = []
    warnings: list[str] = []
    if state.sql_result is None:
        errors.append("SQL result is missing.")
    elif not state.sql_result.columns:
        errors.append("SQL result has no columns.")
    elif state.sql_result.row_count == 0:
        warnings.append("SQL result is empty.")

    state.result_check = ResultCheck(
        is_valid=not errors,
        is_empty=state.sql_result is not None and state.sql_result.row_count == 0,
        needs_repair=bool(errors or warnings),
        errors=errors,
        warnings=warnings,
    )
    return state


def repair_sql_if_needed(
    state: AgentState,
    *,
    data_source: DataSource | None = None,
) -> AgentState:
    """Repair invalid SQL once, or preserve the bounded result-check placeholder."""

    if state.sql_validation is not None and not state.sql_validation.is_valid:
        return _repair_invalid_sql(state, data_source=data_source)

    if state.result_check is None:
        raise ValueError(
            "ResultCheck or invalid SqlValidation is required before SQL repair decision."
        )
    if not state.result_check.needs_repair:
        return state

    repair_attempts = min(state.result_check.repair_attempts + 1, 1)
    state.result_check = state.result_check.model_copy(
        update={
            "repair_attempts": repair_attempts,
            "warnings": [
                *state.result_check.warnings,
                "SQL repair is not implemented in the rule-based result-check path.",
            ],
        }
    )
    return state


def _repair_invalid_sql(state: AgentState, *, data_source: DataSource | None) -> AgentState:
    """Fallback from invalid LLM SQL to deterministic SQL at most once."""

    attempts = state.retry_count_by_node.get(SQL_REPAIR_NODE, 0)
    errors = state.sql_validation.errors if state.sql_validation else []
    if data_source is None or attempts >= 1:
        return _request_sql_clarification(state, errors=errors)

    state.retry_count_by_node[SQL_REPAIR_NODE] = attempts + 1
    state.events.append(
        AgentEvent(
            event_type=EventType.LLM_FALLBACK,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name=SQL_REPAIR_NODE,
            message="SQL validation failed; falling back to rule SQL drafting.",
            payload={
                "fallback_reason": "sql_validation_failed",
                "validation_errors": errors[:5],
                "switched_to_rule_strategy": True,
            },
        )
    )
    try:
        from nodes.sql_nodes import draft_sql

        state.sql_validation = None
        state.sql_result = None
        return draft_sql(state, data_source=data_source, strategy="rule")
    except Exception as exc:  # pragma: no cover - exact failure is covered through graph tests.
        return _request_sql_clarification(state, errors=[*errors, str(exc)])


def _request_sql_clarification(state: AgentState, *, errors: list[str]) -> AgentState:
    """Stop the graph with a structured clarification instead of executing invalid SQL."""

    prompt = "SQL 校验失败，已停止执行。请确认本次分析要使用的指标和维度。"
    if _looks_like_gmv_category_question(state.user_message):
        prompt = "这个品类 GMV 问题应使用现有金额/GMV 字段，还是使用数量乘以商品单价？"
    state.needs_human = True
    state.human_request = HumanRequest(
        request_type=HumanRequestType.BUSINESS_RULE_CONFIRMATION,
        prompt=prompt,
        options=["使用现有 GMV/金额字段", "使用数量 * 单价", "取消"],
        context={
            "reason": "sql_validation_failed",
            "validation_errors": errors[:5],
        },
    )
    state.events.append(
        AgentEvent(
            event_type=EventType.HUMAN_REQUEST,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name=SQL_REPAIR_NODE,
            message=prompt,
            payload=state.human_request.model_dump(mode="json"),
        )
    )
    return state


def _looks_like_gmv_category_question(message: str) -> bool:
    message_lower = message.lower()
    has_gmv = any(
        token in message_lower
        for token in (
            "gmv",
            "\u9500\u552e",
            "\u9500\u552e\u989d",
            "\u6210\u4ea4",
            "\u4ea4\u6613\u989d",
        )
    )
    has_category = any(
        token in message_lower
        for token in ("category", "\u54c1\u7c7b", "\u7c7b\u522b", "\u7c7b\u76ee")
    )
    return has_gmv and has_category
