"""Rule-based nodes for the open exploration workflow."""

from __future__ import annotations

from datasource.base import DataSource
from nodes.chart_nodes import decide_chart
from nodes.execution_nodes import execute_sql
from nodes.final_nodes import build_analysis_package as build_direct_analysis_package
from nodes.insight_nodes import generate_insight
from nodes.planning_nodes import make_analysis_plan
from nodes.result_check_nodes import check_result, repair_sql_if_needed
from nodes.sql_nodes import draft_sql, risk_check_sql, validate_sql
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.database_profile import DatabaseProfile, TableRole
from schemas.direct_analysis import DirectQuestionKind, QuestionInterpretation
from schemas.event import AgentEvent, EventType
from schemas.human import HumanRequest, HumanRequestType
from schemas.insight import Insight
from schemas.open_exploration import (
    ExplorationFinding,
    ExplorationPlan,
    ExplorationSummary,
    ExplorationTopic,
)

MEANINGFUL_METRIC_TOKENS = (
    "gmv",
    "revenue",
    "sales",
    "amount",
    "pos",
    "qtd",
    "qtw",
    "ltd",
    "quantity",
    "qty",
    "price",
    "score",
    "count",
    "orders",
)
MEANINGFUL_DIMENSION_TOKENS = (
    "hq",
    "reseller",
    "reseller_name",
    "category",
    "region",
    "channel",
    "country",
    "city",
    "store",
    "product",
    "name",
)
MEANINGFUL_TIME_TOKENS = ("week", "date", "month", "year", "day")


def route(state: AgentState) -> AgentState:
    """Route the request into open exploration mode."""

    state.command = AgentCommand.EXPLORE
    state.intent = AgentIntent.OPEN_EXPLORATION
    return state


def generate_analysis_map(state: AgentState, *, top_n: int = 3) -> AgentState:
    """Generate candidate exploration topics from DatabaseProfile."""

    profile = _require_profile(state)
    topics: list[ExplorationTopic] = []
    metric_fields = _rank_metric_fields(profile)
    for metric_field in metric_fields[: max(top_n, 3)]:
        table_name, metric_column = _split_qualified_field(metric_field)
        topics.append(_summary_topic(metric_field, metric_column))
        topics.extend(_time_trend_topics(profile, table_name, metric_field, metric_column))
        topics.extend(_top_dimension_topics(profile, table_name, metric_field, metric_column))

    state.exploration_plan = ExplorationPlan(
        topics=topics,
        top_n=top_n,
        requires_human_confirmation=False,
    )
    return state


def rank_topics(state: AgentState) -> AgentState:
    """Rank topics using deterministic priority scores."""

    plan = _require_plan(state)
    profile = _require_profile(state)
    ranked_topics = sorted(
        (
            topic.model_copy(update={"priority_score": _topic_priority(profile, topic)})
            for topic in plan.topics
        ),
        key=lambda topic: (-topic.priority_score, topic.title),
    )
    selected_topic_ids = _select_diverse_topic_ids(ranked_topics, plan.top_n)
    state.exploration_plan = plan.model_copy(
        update={
            "topics": ranked_topics,
            "ranked_topic_ids": [topic.topic_id for topic in ranked_topics],
            "selected_topic_ids": selected_topic_ids,
        }
    )
    return state


def optional_human_confirm(
    state: AgentState,
    *,
    require_confirmation: bool = False,
) -> AgentState:
    """Write an exploration plan confirmation placeholder without interrupting."""

    plan = _require_plan(state)
    state.human_request = HumanRequest(
        request_type=HumanRequestType.EXPLORATION_PLAN_CONFIRMATION,
        prompt="Please confirm the open exploration plan before running analyses.",
        context={
            "topics": [
                {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "question": topic.question,
                    "priority_score": topic.priority_score,
                }
                for topic in plan.topics
            ],
            "selected_topic_ids": plan.selected_topic_ids,
        },
    )
    state.needs_human = require_confirmation
    state.exploration_plan = plan.model_copy(
        update={"requires_human_confirmation": require_confirmation}
    )
    return state


def run_top_n_analyses(
    state: AgentState,
    *,
    data_source: DataSource,
    limit: int | None = 100,
) -> AgentState:
    """Run selected exploration topics through the rule-based direct analysis nodes."""

    plan = _require_plan(state)
    selected_topic_ids = list(plan.selected_topic_ids or plan.ranked_topic_ids[: plan.top_n])
    topics_by_id = {topic.topic_id: topic for topic in plan.topics}
    selected_topics = [
        topics_by_id[topic_id] for topic_id in selected_topic_ids if topic_id in topics_by_id
    ]
    state.exploration_findings = [
        _run_topic_analysis(state, topic, data_source=data_source, limit=limit)
        for topic in selected_topics
    ]
    return state


def summarize_findings(state: AgentState) -> AgentState:
    """Summarize exploration findings into key points."""

    key_points = [_finding_brief(finding) for finding in state.exploration_findings]
    summary = _exploration_summary_text(state.exploration_findings)
    state.exploration_summary = ExplorationSummary(
        findings=state.exploration_findings,
        key_points=key_points,
        summary=summary,
    )
    return state


def build_exploration_package(state: AgentState) -> AgentState:
    """Build an AnalysisPackage from exploration findings."""

    insights = [insight for finding in state.exploration_findings for insight in finding.insights]
    first_completed = next(
        (finding for finding in state.exploration_findings if finding.status == "completed"),
        None,
    )
    state.analysis_package = AnalysisPackage(
        question=state.user_message,
        sql_result=first_completed.sql_result if first_completed else None,
        chart_spec=first_completed.chart_spec if first_completed else None,
        insights=insights,
    )
    return state


def final_response(state: AgentState) -> AgentState:
    """Create final response text for open exploration."""

    if state.analysis_package is None:
        raise ValueError("AnalysisPackage is required before final response.")
    summary = (
        state.exploration_summary.summary
        if state.exploration_summary is not None
        else "开放探索已完成。"
    )
    state.final_response_text = summary
    state.events.append(
        AgentEvent(
            event_type=EventType.TEXT_DELTA,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="final_response",
            message=summary,
        )
    )
    state.events.append(
        AgentEvent(
            event_type=EventType.DONE,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="final_response",
            message="开放探索已完成。",
        )
    )
    return state


def _run_topic_analysis(
    parent_state: AgentState,
    topic: ExplorationTopic,
    *,
    data_source: DataSource,
    limit: int | None,
) -> ExplorationFinding:
    """Run one topic with direct-analysis node functions and return a finding."""

    topic_state = AgentState(
        session_id=parent_state.session_id,
        job_id=parent_state.job_id,
        user_message=topic.question,
        command=AgentCommand.ANALYZE,
        intent=AgentIntent.DIRECT_ANALYSIS,
        datasource_id=parent_state.datasource_id,
        database_profile=parent_state.database_profile,
        profile_status=parent_state.profile_status,
    )
    try:
        table_name, _ = _split_qualified_field(topic.metric_field or "")
        topic_state.question_interpretation = QuestionInterpretation(
            question=topic.question,
            kind=topic.kind,
            table_name=table_name,
            metric_field=topic.metric_field or "",
            time_field=topic.time_field,
            dimension_field=topic.dimension_field,
            top_n=topic.top_n,
        )
        topic_state = make_analysis_plan(topic_state)
        topic_state = draft_sql(topic_state, data_source=data_source)
        topic_state = validate_sql(topic_state, data_source=data_source)
        topic_state = risk_check_sql(topic_state)
        topic_state = execute_sql(topic_state, data_source=data_source, limit=limit)
        for node_fn in (
            check_result,
            repair_sql_if_needed,
            decide_chart,
            generate_insight,
            build_direct_analysis_package,
        ):
            topic_state = node_fn(topic_state)
    except Exception as exc:
        return ExplorationFinding(
            topic=topic,
            title=_topic_label(topic),
            question=topic.question,
            metric_name=_field_label(topic.metric_field),
            dimension_name=_field_label(topic.dimension_field),
            confidence=0.0,
            status="failed",
            errors=[str(exc)],
        )

    result_summary = _result_summary(topic, topic_state)
    business_interpretation = _business_interpretation(topic, topic_state, result_summary)
    limitations = _topic_limitations(topic)
    insight = Insight(
        title=_topic_label(topic),
        summary=business_interpretation,
        evidence=[result_summary] if result_summary else [],
        confidence=_topic_confidence(topic),
    )
    return ExplorationFinding(
        topic=topic,
        title=_topic_label(topic),
        question=topic.question,
        metric_name=_field_label(topic.metric_field),
        dimension_name=_field_label(topic.dimension_field),
        sql=topic_state.sql_draft.query if topic_state.sql_draft else None,
        sql_result=topic_state.sql_result,
        result_summary=result_summary,
        business_interpretation=business_interpretation,
        chart_spec=topic_state.chart_spec,
        chart_type=(
            topic_state.chart_spec.chart_type.value if topic_state.chart_spec is not None else None
        ),
        confidence=_topic_confidence(topic),
        limitations=limitations,
        insights=[insight],
        status="completed",
    )


def _exploration_summary_text(findings: list[ExplorationFinding]) -> str:
    """生成面向用户的中文开放探索摘要。"""

    if not findings:
        return "开放探索未产生可用发现，请先确认数据源画像是否完整。"

    completed = [finding for finding in findings if finding.status == "completed"]
    failed_count = len(findings) - len(completed)
    lines = [f"已完成开放探索，自动分析了 {len(completed)} 个方向："]
    for index, finding in enumerate(completed, start=1):
        lines.append(f"{index}. {_topic_label(finding.topic)}：{_finding_brief(finding)}")
    if failed_count:
        lines.append(f"另有 {failed_count} 个方向暂未生成可用结果。")
    lines.extend(
        [
            "可继续追问：你可以指定某个方向继续深挖，或要求按时间、品类、地区等维度展开。",
            "可导出：可以继续确认生成报告、Excel、PPT 或 Dashboard。",
        ]
    )
    return "\n".join(lines)


def _finding_brief(finding: ExplorationFinding) -> str:
    """返回单个探索方向的短发现。"""

    if finding.status != "completed":
        return "该方向暂未生成可用结果。"
    if finding.business_interpretation:
        return finding.business_interpretation
    if finding.insights:
        return finding.insights[0].summary
    if finding.sql_result is not None:
        return f"已返回 {finding.sql_result.row_count} 行结果。"
    return "已完成该方向的基础分析。"


def _topic_label(topic: ExplorationTopic) -> str:
    """把结构化探索 topic 转成简短中文方向名。"""

    metric_name = _field_label(topic.metric_field)
    if topic.kind is DirectQuestionKind.TIME_TREND and topic.time_field:
        return f"{metric_name} 随 {_field_label(topic.time_field)} 的趋势"
    if topic.kind is DirectQuestionKind.TOP_N and topic.dimension_field:
        dimension_name = _field_label(topic.dimension_field)
        return f"按 {dimension_name} 排名的 {metric_name} Top {topic.top_n or 5}"
    if topic.kind is DirectQuestionKind.SUMMARY:
        return f"{metric_name} 汇总"
    return topic.title


def _field_label(field: str | None) -> str:
    """返回字段的列名部分，避免把内部对象塞进用户回复。"""

    if not field:
        return "指标"
    return field.split(".", maxsplit=1)[-1]


def _result_summary(topic: ExplorationTopic, topic_state: AgentState) -> str:
    """从查询结果中提炼一句稳定摘要。"""

    query_result = topic_state.sql_result
    if query_result is None or not query_result.rows:
        return "未返回可用结果。"
    first_row = query_result.rows[0]
    metric_name = _field_label(topic.metric_field)
    if topic.kind is DirectQuestionKind.TIME_TREND and topic.time_field:
        metric_column = _metric_result_column(first_row, metric_name)
        time_column = _field_label(topic.time_field)
        best_row = _max_row(query_result.rows, metric_column)
        time_value = best_row.get(time_column, "首个时间点")
        metric_value = best_row.get(metric_column)
        return f"按 {time_column} 观察 {metric_name}，{time_value} 的数值最高，为 {metric_value}。"
    if topic.kind is DirectQuestionKind.TOP_N and topic.dimension_field:
        dimension_name = _field_label(topic.dimension_field)
        metric_column = _metric_result_column(first_row, metric_name)
        dimension_value = first_row.get(dimension_name, "排名第一项")
        metric_value = first_row.get(metric_column)
        return (
            f"按 {dimension_name} 对比 {metric_name}，"
            f"{dimension_value} 排名第一，数值为 {metric_value}。"
        )
    metric_column = _metric_result_column(first_row, metric_name)
    return f"{metric_name} 汇总结果为 {first_row.get(metric_column)}。"


def _business_interpretation(
    topic: ExplorationTopic,
    topic_state: AgentState,
    result_summary: str,
) -> str:
    """把结果摘要包装成用户可读的业务解释。"""

    limitations = _topic_limitations(topic)
    if limitations:
        return f"{result_summary} 限制：{'；'.join(limitations)}"
    chart_text = ""
    if topic_state.chart_spec is not None:
        chart_text = f" 建议用 {topic_state.chart_spec.chart_type.value} 图查看。"
    return f"{result_summary}{chart_text}"


def _metric_result_column(row: dict[str, object], metric_name: str) -> str:
    """Find the metric value column in a SQL result row."""

    if metric_name in row:
        return metric_name
    for column_name in row:
        lowered = column_name.lower()
        if metric_name.lower() in lowered or lowered.startswith(("total_", "avg_")):
            return column_name
    return next(iter(row))


def _max_row(rows: list[dict[str, object]], metric_column: str) -> dict[str, object]:
    """Return the row with the highest numeric value for a metric column."""

    return max(rows, key=lambda row: _numeric_value(row.get(metric_column)))


def _numeric_value(value: object) -> float:
    """Convert common numeric values for ranking summaries."""

    try:
        return float(value) if value is not None else float("-inf")
    except (TypeError, ValueError):
        return float("-inf")


def _summary_topic(metric_field: str, metric_column: str) -> ExplorationTopic:
    """Create a summary topic for one metric."""

    return ExplorationTopic(
        title=f"Summary of {metric_column}",
        question=f"What is total {metric_column}?",
        kind=DirectQuestionKind.SUMMARY,
        metric_field=metric_field,
        rationale="Core metric summary.",
    )


def _time_trend_topics(
    profile: DatabaseProfile,
    table_name: str,
    metric_field: str,
    metric_column: str,
) -> list[ExplorationTopic]:
    """Create time trend topics for same-table time fields."""

    topics = []
    for time_field in _rank_time_fields(profile, table_name):
        _, time_column = _split_qualified_field(time_field)
        topics.append(
            ExplorationTopic(
                title=f"{metric_column} trend by {time_column}",
                question=f"Show {time_column} {metric_column} trend",
                kind=DirectQuestionKind.TIME_TREND,
                metric_field=metric_field,
                time_field=time_field,
                rationale="Time trend over core metric.",
            )
        )
    return topics


def _top_dimension_topics(
    profile: DatabaseProfile,
    table_name: str,
    metric_field: str,
    metric_column: str,
) -> list[ExplorationTopic]:
    """Create TopN topics for same-table dimensions."""

    dimension_fields = _rank_dimension_fields(profile, table_name)
    if not dimension_fields:
        dimension_fields = _identifier_dimension_fields(profile, table_name)

    topics = []
    for dimension_field in dimension_fields:
        _, dimension_column = _split_qualified_field(dimension_field)
        topics.append(
            ExplorationTopic(
                title=f"Top {dimension_column} by {metric_column}",
                question=f"Top 5 {metric_column} by {dimension_column}",
                kind=DirectQuestionKind.TOP_N,
                metric_field=metric_field,
                dimension_field=dimension_field,
                top_n=5,
                rationale="Rank core dimension by metric.",
            )
        )
    return topics


def _topic_priority(profile: DatabaseProfile, topic: ExplorationTopic) -> float:
    """Score topics so time trends, core metrics, and dimensions are prioritized."""

    metric_score = _metric_quality_score(profile, topic.metric_field)
    dimension_score = (
        _field_semantic_score(topic.dimension_field, MEANINGFUL_DIMENSION_TOKENS)
        if topic.dimension_field
        else 0
    )
    time_score = _time_field_priority(topic.time_field)
    if topic.kind is DirectQuestionKind.TIME_TREND:
        return 120 + metric_score + time_score
    if topic.kind is DirectQuestionKind.TOP_N:
        return 110 + metric_score + dimension_score
    if topic.kind is DirectQuestionKind.SUMMARY:
        return 70 + metric_score
    return 0


def _select_diverse_topic_ids(
    ranked_topics: list[ExplorationTopic],
    top_n: int,
) -> list[str]:
    """Pick a small set that preserves exploration variety before pure score order."""

    selected: list[str] = []
    topics_by_id = {topic.topic_id: topic for topic in ranked_topics}
    for required_kind in (DirectQuestionKind.TIME_TREND, DirectQuestionKind.TOP_N):
        topic = next(
            (
                candidate
                for candidate in ranked_topics
                if candidate.kind is required_kind and candidate.topic_id not in selected
            ),
            None,
        )
        if topic is not None:
            selected.append(topic.topic_id)
        if len(selected) >= top_n:
            return selected

    selected_kinds = {topics_by_id[topic_id].kind for topic_id in selected}
    for topic in ranked_topics:
        if topic.topic_id in selected:
            continue
        if topic.kind is DirectQuestionKind.TIME_TREND and topic.kind in selected_kinds:
            continue
        selected.append(topic.topic_id)
        selected_kinds.add(topic.kind)
        if len(selected) >= top_n:
            break
    if len(selected) >= top_n:
        return selected

    for topic in ranked_topics:
        if topic.topic_id in selected:
            continue
        selected.append(topic.topic_id)
        if len(selected) >= top_n:
            break
    return selected


def _rank_metric_fields(profile: DatabaseProfile) -> list[str]:
    """Return metric fields with semantically meaningful names first."""

    metric_fields = profile.candidate_metrics or profile.metric_fields
    if not metric_fields:
        return []
    ranked = sorted(
        metric_fields,
        key=lambda field: (-_metric_quality_score(profile, field), field),
    )
    meaningful = [field for field in ranked if _metric_quality_score(profile, field) > 0]
    return meaningful or ranked[:1]


def _metric_quality_score(profile: DatabaseProfile, field: str) -> int:
    """Score metric fields; anonymous numeric columns are kept as weak fallbacks only."""

    table_name, column_name = _split_qualified_field(field)
    column_lower = column_name.lower()
    score = _field_semantic_score(field, MEANINGFUL_METRIC_TOKENS)
    if column_lower == "gmv":
        score += 120
    elif column_lower == "item_gmv":
        score += 110
    elif column_lower == "sales_amount":
        score += 80
    elif column_lower == "amount":
        score += 70
    if _is_anonymous_column(column_name):
        score -= 80
    if _table_role(profile, table_name) is TableRole.FACT:
        score += 10
    return score


def _time_field_priority(field: str | None) -> int:
    """Prefer month buckets for trend topics when the profile offers them."""

    if not field:
        return 0
    _, column_name = _split_qualified_field(field)
    column_lower = column_name.lower()
    score = _field_semantic_score(field, MEANINGFUL_TIME_TOKENS)
    if column_lower == "order_month":
        score += 60
    elif column_lower.endswith("_month"):
        score += 50
    elif column_lower == "order_date":
        score += 40
    elif column_lower.endswith("_date"):
        score += 30
    return score


def _rank_time_fields(profile: DatabaseProfile, table_name: str) -> list[str]:
    """Prefer same-table and clearly named time fields."""

    return sorted(
        _same_table_fields(profile.time_fields, table_name),
        key=lambda field: (
            0 if field.endswith(".order_month") else 1,
            0 if field.endswith(".order_date") else 1,
            -_field_semantic_score(field, MEANINGFUL_TIME_TOKENS),
            field,
        ),
    )


def _rank_dimension_fields(profile: DatabaseProfile, table_name: str) -> list[str]:
    """Prefer human-readable business dimensions over ids and anonymous labels."""

    dimension_fields = [
        field
        for field in _same_table_fields(profile.candidate_dimensions, table_name)
        if field not in profile.time_fields
    ]
    return sorted(
        dimension_fields,
        key=lambda field: (-_field_semantic_score(field, MEANINGFUL_DIMENSION_TOKENS), field),
    )


def _field_semantic_score(field: str | None, tokens: tuple[str, ...]) -> int:
    """Score a qualified field name using domain-oriented token hints."""

    if not field:
        return 0
    _, column_name = _split_qualified_field(field)
    column_lower = column_name.lower()
    score = 0
    for token in tokens:
        if token in column_lower:
            score += 25
    if _is_anonymous_column(column_name):
        score -= 50
    return score


def _table_role(profile: DatabaseProfile, table_name: str) -> TableRole:
    """Return a table role, defaulting to unknown."""

    for table in profile.tables:
        if table.name == table_name:
            return table.role
    return TableRole.UNKNOWN


def _is_anonymous_column(column_name: str) -> bool:
    """Return whether a column looks like a generated anonymous spreadsheet column."""

    lowered = column_name.lower()
    if lowered.startswith("column_") and lowered.removeprefix("column_").isdigit():
        return True
    if lowered.startswith("unnamed"):
        return True
    return False


def _topic_confidence(topic: ExplorationTopic) -> float:
    """Estimate confidence from field semantics only; no LLM involved."""

    score = _field_semantic_score(topic.metric_field, MEANINGFUL_METRIC_TOKENS)
    if topic.dimension_field:
        score += _field_semantic_score(topic.dimension_field, MEANINGFUL_DIMENSION_TOKENS)
    if _topic_limitations(topic):
        return 0.45
    return 0.85 if score > 0 else 0.65


def _topic_limitations(topic: ExplorationTopic) -> list[str]:
    """Return limitations for fields whose business meaning is weak."""

    limitations: list[str] = []
    for field in (topic.metric_field, topic.dimension_field):
        if field is None:
            continue
        _, column_name = _split_qualified_field(field)
        if _is_anonymous_column(column_name):
            limitations.append(f"{column_name} 字段缺少业务含义，仅作为数值指标候选展示。")
    return limitations


def _identifier_dimension_fields(profile: DatabaseProfile, table_name: str) -> list[str]:
    """Return same-table identifier fields that can be used for TopN topics."""

    fields: list[str] = []
    for table in profile.tables:
        if table.name != table_name:
            continue
        for column in table.columns:
            if column.name.endswith("_id") and column.name != "id":
                fields.append(f"{table.name}.{column.name}")
    return fields


def _same_table_fields(fields: list[str], table_name: str) -> list[str]:
    """Filter qualified fields to one table."""

    return [field for field in fields if _split_qualified_field(field)[0] == table_name]


def _require_profile(state: AgentState) -> DatabaseProfile:
    if state.database_profile is None:
        raise ValueError("DatabaseProfile is required before open exploration.")
    return state.database_profile


def _require_plan(state: AgentState) -> ExplorationPlan:
    if state.exploration_plan is None:
        raise ValueError("ExplorationPlan is required for open exploration.")
    return state.exploration_plan


def _split_qualified_field(field: str) -> tuple[str, str]:
    table_name, column_name = field.split(".", maxsplit=1)
    return table_name, column_name
