"""Rule-based planning nodes for direct analysis."""

from __future__ import annotations

import re

from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from schemas.agent_state import AgentState
from schemas.analysis_plan import AnalysisMode, AnalysisPlan, AnalysisStep
from schemas.database_profile import DatabaseProfile, FieldSemanticType
from schemas.direct_analysis import DirectQuestionKind, QuestionInterpretation


def interpret_question(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Interpret a direct analysis question using rule or LLM strategy."""

    if strategy == "llm":
        try:
            return _interpret_question_with_llm(
                state,
                llm_client=llm_client,
                prompt_loader=prompt_loader,
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="interpret_question",
                prompt_name="analysis_planner",
                llm_client=llm_client,
                exc=exc,
            )
            return _interpret_question_with_rules(state)
    return _interpret_question_with_rules(state)


def make_analysis_plan(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Build an AnalysisPlan using rule defaults or a narrow LLM prompt."""

    if strategy == "llm":
        try:
            return _make_analysis_plan_with_llm(
                state,
                llm_client=llm_client,
                prompt_loader=prompt_loader,
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="make_analysis_plan",
                prompt_name="analysis_planner",
                llm_client=llm_client,
                exc=exc,
            )
            return _make_analysis_plan_with_rules(state)
    return _make_analysis_plan_with_rules(state)


def _interpret_question_with_rules(state: AgentState) -> AgentState:
    """Interpret a direct analysis question using deterministic rules."""

    profile = _require_profile(state)
    question = state.user_message.strip()
    previous = state.last_question_interpretation if state.is_followup_correction else None
    effective_question = _effective_question(state, previous)
    question_lower = effective_question.lower()
    kind = _detect_question_kind(question_lower)
    if previous is not None and _is_metric_only_correction(question):
        kind = previous.kind
    time_field = (
        _select_time_field(profile, question_lower)
        if kind is DirectQuestionKind.TIME_TREND
        else None
    )
    metric_aggregation = _detect_metric_aggregation(question_lower, previous)
    metric_field = _select_metric_field(
        profile,
        question_lower,
        preferred_table=_table_name_from_field(time_field),
        metric_aggregation=metric_aggregation,
    )
    table_name, _ = _split_qualified_field(metric_field)
    if kind is DirectQuestionKind.TIME_TREND:
        time_field = _select_time_field(profile, question_lower, preferred_table=table_name)
    dimension_field = None
    if kind is DirectQuestionKind.TOP_N:
        if (
            previous is not None
            and previous.dimension_field
            and not _asks_for_new_dimension(question)
        ):
            dimension_field = _equivalent_dimension_field(
                profile,
                preferred_table=table_name,
                previous_dimension_field=previous.dimension_field,
            )
        dimension_field = dimension_field or _select_dimension_field(
            profile,
            table_name,
            question_lower,
        )

    if kind is DirectQuestionKind.TIME_TREND and time_field is None:
        raise ValueError("Time trend question requires a candidate time field.")
    if kind is DirectQuestionKind.TOP_N and dimension_field is None:
        raise ValueError("TopN question requires a candidate dimension field.")

    top_n = None
    if kind is DirectQuestionKind.TOP_N:
        if previous is not None and _is_metric_only_correction(question) and previous.top_n:
            top_n = previous.top_n
        else:
            top_n = _extract_top_n(question_lower)

    state.question_interpretation = QuestionInterpretation(
        question=question,
        kind=kind,
        table_name=table_name,
        metric_field=metric_field,
        metric_aggregation=metric_aggregation,
        time_field=time_field,
        dimension_field=dimension_field,
        top_n=top_n,
    )
    return state


def _make_analysis_plan_with_rules(state: AgentState) -> AgentState:
    """Build an AnalysisPlan from the structured question interpretation."""

    interpretation = _require_interpretation(state)
    state.analysis_plan = AnalysisPlan(
        mode=AnalysisMode.DIRECT,
        question=state.user_message,
        steps=[
            AnalysisStep(
                name="draft_sql",
                objective=f"Generate read-only SQL for {interpretation.kind.value}.",
                required_inputs=["database_profile", "question_interpretation"],
                expected_outputs=["sql_draft"],
                tool_categories=["sql"],
            ),
            AnalysisStep(
                name="validate_sql",
                objective="Validate SQL safety and referenced schema fields.",
                required_inputs=["sql_draft", "database_profile"],
                expected_outputs=["sql_validation"],
            ),
            AnalysisStep(
                name="execute_sql",
                objective="Run guarded read-only SQL.",
                required_inputs=["sql_validation"],
                expected_outputs=["sql_result"],
                tool_categories=["sql"],
            ),
            AnalysisStep(
                name="summarize",
                objective="Check results, choose chart type, and write rule-based insight.",
                required_inputs=["sql_result"],
                expected_outputs=["analysis_package"],
            ),
        ],
        assumptions=[
            "Rule-based planning only; no LLM interpretation was used.",
            f"Metric selected: {interpretation.metric_field}.",
        ],
    )
    return state


def _interpret_question_with_llm(
    state: AgentState,
    *,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> AgentState:
    """Interpret a direct question from a narrow JSON LLM response."""

    profile = _require_profile(state)
    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="analysis_planner",
        prompt_loader=prompt_loader,
        state=state,
        node_name="interpret_question",
        user_payload={
            "task": "interpret_question",
            "user_message": state.user_message,
            "database_profile": profile.model_dump(mode="json"),
            "previous_analysis_summary": _previous_analysis_summary(state),
            "agent_context_summary": (
                state.context_summary.model_dump(mode="json")
                if state.context_summary is not None
                else None
            ),
            "is_followup_correction": state.is_followup_correction,
        },
    )
    state.question_interpretation = QuestionInterpretation(
        question=payload.get("question", state.user_message),
        kind=DirectQuestionKind(payload["kind"]),
        table_name=payload["table_name"],
        metric_field=payload["metric_field"],
        metric_aggregation=payload.get("metric_aggregation", "sum"),
        time_field=payload.get("time_field"),
        dimension_field=payload.get("dimension_field"),
        top_n=payload.get("top_n"),
    )
    return state


def _make_analysis_plan_with_llm(
    state: AgentState,
    *,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> AgentState:
    """Build an AnalysisPlan from a narrow JSON LLM response."""

    interpretation = _require_interpretation(state)
    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="analysis_planner",
        prompt_loader=prompt_loader,
        state=state,
        node_name="make_analysis_plan",
        user_payload={
            "task": "make_analysis_plan",
            "user_message": state.user_message,
            "question_interpretation": interpretation.model_dump(mode="json"),
            "previous_analysis_summary": _previous_analysis_summary(state),
            "agent_context_summary": (
                state.context_summary.model_dump(mode="json")
                if state.context_summary is not None
                else None
            ),
            "is_followup_correction": state.is_followup_correction,
        },
    )
    state.analysis_plan = AnalysisPlan(
        mode=AnalysisMode.DIRECT,
        question=state.user_message,
        steps=[
            AnalysisStep(
                name=step["name"],
                objective=step["objective"],
                required_inputs=step.get("required_inputs", []),
                expected_outputs=step.get("expected_outputs", []),
                tool_categories=step.get("tool_categories", []),
            )
            for step in payload.get("steps", [])
        ],
        assumptions=payload.get("assumptions", []),
        risks=payload.get("risks", []),
        requires_human_confirmation=payload.get("requires_human_confirmation", False),
    )
    return state


def _require_profile(state: AgentState) -> DatabaseProfile:
    if state.database_profile is None:
        raise ValueError("DatabaseProfile is required before question interpretation.")
    return state.database_profile


def _require_interpretation(state: AgentState) -> QuestionInterpretation:
    if state.question_interpretation is None:
        raise ValueError("QuestionInterpretation is required before plan creation.")
    return state.question_interpretation


def _detect_question_kind(question_lower: str) -> DirectQuestionKind:
    if any(
        token in question_lower
        for token in (
            "trend",
            "over time",
            "monthly",
            "by month",
            "\u8d8b\u52bf",
            "\u6309\u6708",
            "\u8fd1 12 \u4e2a\u6708",
            "\u8fd112\u4e2a\u6708",
        )
    ):
        return DirectQuestionKind.TIME_TREND
    if any(
        token in question_lower
        for token in (
            "top",
            "highest",
            "largest",
            "rank",
            "\u524d",
            "\u6700\u9ad8",
            "\u6700\u5927",
            "\u6700\u591a",
            "\u6392\u540d",
            "\u6392\u884c",
        )
    ):
        return DirectQuestionKind.TOP_N
    return DirectQuestionKind.SUMMARY


def _extract_top_n(question_lower: str) -> int:
    match = re.search(r"top\s*(\d+)", question_lower, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\u524d\s*(\d+)", question_lower)
    if match:
        return int(match.group(1))
    if any(token in question_lower for token in ("highest", "largest", "最高", "最大", "最多")):
        return 1
    return 5


def _select_metric_field(
    profile: DatabaseProfile,
    question_lower: str,
    *,
    preferred_table: str | None = None,
    metric_aggregation: str = "sum",
) -> str:
    candidate_metrics = profile.candidate_metrics or profile.metric_fields
    if not candidate_metrics:
        raise ValueError("DatabaseProfile has no candidate metric fields.")

    return sorted(
        candidate_metrics,
        key=lambda field: _metric_field_score(
            field,
            question_lower,
            preferred_table,
            metric_aggregation,
        ),
    )[0]


def _select_time_field(
    profile: DatabaseProfile,
    question_lower: str,
    *,
    preferred_table: str | None = None,
) -> str | None:
    time_fields = profile.time_fields
    if not time_fields:
        return None

    preferred_time_fields = _rank_time_fields(profile, preferred_table=preferred_table)
    for field in preferred_time_fields:
        _, column_name = _split_qualified_field(field)
        if column_name.lower() in question_lower:
            return field
    return preferred_time_fields[0] if preferred_time_fields else None


def _select_dimension_field(
    profile: DatabaseProfile,
    table_name: str,
    question_lower: str,
) -> str | None:
    identifier_field = _first_identifier_field(profile, table_name)
    if identifier_field is not None:
        _, identifier_column = _split_qualified_field(identifier_field)
        if identifier_column.lower() in question_lower:
            return identifier_field

    candidate_dimensions = profile.candidate_dimensions or profile.dimension_fields
    if not candidate_dimensions:
        return identifier_field

    ranked_dimensions = sorted(
        candidate_dimensions,
        key=lambda field: _dimension_field_score(profile, field, table_name, question_lower),
    )
    best_dimension = ranked_dimensions[0] if ranked_dimensions else None
    if best_dimension is not None:
        return best_dimension

    return identifier_field


def _metric_field_score(
    field: str,
    question_lower: str,
    preferred_table: str | None,
    metric_aggregation: str,
) -> tuple[int, str]:
    table_name, column_name = _split_qualified_field(field)
    column_lower = column_name.lower()
    score = 100
    if table_name == preferred_table:
        score -= 20
    if column_lower in question_lower:
        score -= 40
    if metric_aggregation == "avg" and _asks_for_average_unit_price(question_lower):
        if table_name == "order_items" and column_lower == "unit_price":
            score -= 180
        elif column_lower == "unit_price":
            score -= 160
        elif column_lower == "price":
            score -= 120
        elif column_lower in {"amount", "sales_amount", "gmv", "item_gmv"}:
            score -= 20
    if _asks_for_gmv(question_lower):
        if _asks_for_chinese_category(question_lower) and field == "order_items.item_gmv":
            score -= 150
        elif column_lower in {"gmv", "item_gmv"}:
            score -= 80
        elif column_lower in {"sales_amount", "amount", "revenue"}:
            score -= 70
        elif column_lower in {"quantity", "qty"}:
            score -= 30
        elif "price" in column_lower:
            score -= 10
    return score, field


def _dimension_field_score(
    profile: DatabaseProfile,
    field: str,
    metric_table_name: str,
    question_lower: str,
) -> tuple[int, str]:
    table_name, column_name = _split_qualified_field(field)
    column_lower = column_name.lower()
    score = 100
    if column_lower in question_lower:
        score -= 40
    if _asks_for_category(question_lower) and column_lower == "category":
        score -= 80
    if _asks_for_product(question_lower) and column_lower in {"product_name", "name", "product"}:
        score -= 85
    if table_name == metric_table_name:
        score -= 25
    elif table_name in _directly_related_tables(profile, metric_table_name):
        score -= 20
    if _asks_for_category(question_lower) and table_name == "products":
        score -= 10
    if _asks_for_product(question_lower) and table_name == "products":
        score -= 15
    return score, field


def _asks_for_gmv(question_lower: str) -> bool:
    return any(
        token in question_lower
        for token in (
            "gmv",
            "sales",
            "revenue",
            "amount",
            "\u9500\u552e",
            "\u9500\u552e\u989d",
            "\u6210\u4ea4",
            "\u4ea4\u6613\u989d",
        )
    )


def _asks_for_average_unit_price(question_lower: str) -> bool:
    return any(
        token in question_lower
        for token in (
            "average unit price",
            "avg unit price",
            "unit price",
            "average price",
            "avg price",
            "平均单价",
            "销售单价",
            "单价",
            "均价",
        )
    ) and any(token in question_lower for token in ("average", "avg", "平均", "均价", "单价"))


def _detect_metric_aggregation(
    question_lower: str,
    previous: QuestionInterpretation | None,
) -> str:
    if _asks_for_average_unit_price(question_lower):
        return "avg"
    if previous is not None:
        return previous.metric_aggregation
    if any(token in question_lower for token in ("average", "avg", "平均", "均值")):
        return "avg"
    return "sum"


def _effective_question(
    state: AgentState,
    previous: QuestionInterpretation | None,
) -> str:
    if previous is None:
        return state.user_message.strip()
    pieces = [
        state.last_user_question or previous.question,
        state.user_message,
    ]
    return " ".join(piece for piece in pieces if piece).strip()


def _is_metric_only_correction(question: str) -> bool:
    lowered = question.lower()
    return _asks_for_average_unit_price(lowered) and not _asks_for_new_dimension(question)


def _asks_for_new_dimension(question: str) -> bool:
    lowered = question.lower()
    return any(
        token in lowered
        for token in (
            "商品",
            "产品",
            "product",
            "地区",
            "region",
            "渠道",
            "channel",
            "用户",
            "customer",
        )
    )


def _equivalent_dimension_field(
    profile: DatabaseProfile,
    *,
    preferred_table: str,
    previous_dimension_field: str,
) -> str:
    _, previous_column = _split_qualified_field(previous_dimension_field)
    for table in profile.tables:
        if table.name != preferred_table:
            continue
        if any(column.name == previous_column for column in table.columns):
            return f"{preferred_table}.{previous_column}"
    return previous_dimension_field


def _previous_analysis_summary(state: AgentState) -> dict[str, object] | None:
    if state.last_question_interpretation is None:
        return None
    return {
        "last_user_question": state.last_user_question,
        "last_question_interpretation": state.last_question_interpretation.model_dump(mode="json"),
        "last_sql_draft": (
            state.last_sql_draft.model_dump(mode="json") if state.last_sql_draft else None
        ),
        "last_sql_result_summary": state.last_sql_result_summary,
        "last_chart_spec": (
            state.last_chart_spec.model_dump(mode="json") if state.last_chart_spec else None
        ),
    }


def _asks_for_category(question_lower: str) -> bool:
    return any(
        token in question_lower
        for token in ("category", "categories", "\u54c1\u7c7b", "\u7c7b\u522b", "\u7c7b\u76ee")
    )


def _asks_for_product(question_lower: str) -> bool:
    return any(
        token in question_lower
        for token in ("product", "products", "product_name", "商品", "产品", "货品")
    )


def _asks_for_chinese_category(question_lower: str) -> bool:
    return any(
        token in question_lower for token in ("\u54c1\u7c7b", "\u7c7b\u522b", "\u7c7b\u76ee")
    )


def _directly_related_tables(profile: DatabaseProfile, table_name: str) -> set[str]:
    related: set[str] = set()
    for relationship in profile.relationships:
        if relationship.from_table == table_name:
            related.add(relationship.to_table)
        if relationship.to_table == table_name:
            related.add(relationship.from_table)
    return related


def _first_identifier_field(profile: DatabaseProfile, table_name: str) -> str | None:
    for table in profile.tables:
        if table.name != table_name:
            continue
        for column in table.columns:
            if column.semantic_type is FieldSemanticType.IDENTIFIER and column.name != "id":
                return f"{table.name}.{column.name}"
    return None


def _rank_time_fields(
    profile: DatabaseProfile,
    *,
    preferred_table: str | None,
) -> list[str]:
    """Rank profile time fields for deterministic time-trend planning."""

    return sorted(
        profile.time_fields,
        key=lambda field: (
            0 if field == "orders.order_month" else 1,
            0 if field == "orders.order_date" else 1,
            0 if _table_name_from_field(field) == preferred_table else 1,
            0 if _table_role_for_field(profile, field) == "fact" else 1,
            field,
        ),
    )


def _prefer_fields_by_table(fields: list[str], preferred_table: str | None) -> list[str]:
    """Return fields with preferred-table entries first while preserving fallback options."""

    if preferred_table is None:
        return fields
    preferred = [field for field in fields if _table_name_from_field(field) == preferred_table]
    remaining = [field for field in fields if _table_name_from_field(field) != preferred_table]
    return [*preferred, *remaining]


def _table_role_for_field(profile: DatabaseProfile, field: str) -> str | None:
    """Return the profile role of a qualified field's table."""

    table_name = _table_name_from_field(field)
    if table_name is None:
        return None
    for table in profile.tables:
        if table.name == table_name:
            return table.role.value
    return None


def _table_name_from_field(field: str | None) -> str | None:
    """Return the table part of a qualified field reference."""

    if field is None or "." not in field:
        return None
    table_name, _ = _split_qualified_field(field)
    return table_name


def _split_qualified_field(field: str) -> tuple[str, str]:
    table_name, column_name = field.split(".", maxsplit=1)
    return table_name, column_name
