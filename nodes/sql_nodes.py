"""Rule-based SQL drafting and validation nodes."""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

from datasource.base import DataSource
from guards.sql_guard import validate_select_only_sql
from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from schemas.agent_state import AgentState
from schemas.database_profile import DatabaseProfile
from schemas.direct_analysis import DirectQuestionKind, QuestionInterpretation
from schemas.sql import SqlDialect, SqlDraft, SqlValidation, SqlValidationStatus

GMV_TOKENS = (
    "gmv",
    "sales",
    "revenue",
    "amount",
    "\u9500\u552e",
    "\u9500\u552e\u989d",
    "\u6210\u4ea4",
    "\u4ea4\u6613\u989d",
)
CATEGORY_TOKENS = ("category", "categories", "\u54c1\u7c7b", "\u7c7b\u522b", "\u7c7b\u76ee")
DIRECT_AMOUNT_COLUMNS = ("gmv", "item_gmv", "sales_amount", "amount", "revenue")
PRICE_COLUMNS = ("unit_price", "price")
QUANTITY_COLUMNS = ("quantity", "qty")


def draft_sql(
    state: AgentState,
    *,
    data_source: DataSource,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Draft read-only SQL using rule defaults or a narrow LLM prompt."""

    if strategy == "llm":
        try:
            return _draft_sql_with_llm(
                state,
                data_source=data_source,
                llm_client=llm_client,
                prompt_loader=prompt_loader,
            )
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="draft_sql",
                prompt_name="sql_drafter",
                llm_client=llm_client,
                exc=exc,
            )
            return _draft_sql_with_rules(state, data_source=data_source)
    return _draft_sql_with_rules(state, data_source=data_source)


def _draft_sql_with_rules(state: AgentState, *, data_source: DataSource) -> AgentState:
    """Draft simple read-only SQL from a structured question interpretation."""

    interpretation = _require_interpretation(state)
    metric_table, metric_column = _split_qualified_field(interpretation.metric_field)
    if metric_table != interpretation.table_name:
        raise ValueError("Metric field table does not match interpretation table.")

    if interpretation.kind is DirectQuestionKind.TIME_TREND:
        if interpretation.time_field is None:
            raise ValueError("Time trend SQL requires a time field.")
        _, time_column = _split_qualified_field(interpretation.time_field)
        aggregate = _aggregate_function(interpretation.metric_aggregation)
        alias = _aggregate_alias(metric_column, interpretation.metric_aggregation)
        query = (
            f"SELECT {time_column}, {aggregate}({metric_column}) AS {alias} "
            f"FROM {interpretation.table_name} "
            f"GROUP BY {time_column} "
            f"ORDER BY {time_column}"
        )
        used_fields = [interpretation.time_field, interpretation.metric_field]
    elif interpretation.kind is DirectQuestionKind.TOP_N:
        if interpretation.dimension_field is None:
            raise ValueError("TopN SQL requires a dimension field.")
        query, used_fields = _draft_top_n_sql(state, interpretation)
    else:
        aggregate = _aggregate_function(interpretation.metric_aggregation)
        alias = _aggregate_alias(metric_column, interpretation.metric_aggregation)
        query = f"SELECT {aggregate}({metric_column}) AS {alias} FROM {interpretation.table_name}"
        used_fields = [interpretation.metric_field]

    guard_result = validate_select_only_sql(query, dialect=data_source.dialect)
    state.sql_draft = SqlDraft(
        query=query,
        dialect=_sql_dialect(data_source.dialect),
        rationale=f"Rule-based SQL for {interpretation.kind.value}.",
        referenced_tables=guard_result.referenced_tables,
        referenced_columns=guard_result.referenced_columns,
        used_tables=guard_result.referenced_tables,
        used_fields=_dedupe(used_fields),
        generation_strategy="rule",
    )
    return state


def _draft_top_n_sql(
    state: AgentState,
    interpretation: QuestionInterpretation,
) -> tuple[str, list[str]]:
    """Draft a bounded TopN query, including one-hop joins when the profile proves them."""

    profile = _require_profile(state)
    metric_table, metric_column = _split_qualified_field(interpretation.metric_field)
    dimension_table, dimension_column = _split_qualified_field(interpretation.dimension_field or "")
    top_n = interpretation.top_n or 5
    asks_gmv = _asks_for_gmv(interpretation.question)
    aggregate = _aggregate_function(interpretation.metric_aggregation)

    if metric_table == dimension_table:
        metric_expr = metric_column
        dimension_expr = dimension_column
        from_clause = metric_table
        alias = _metric_alias(
            metric_column,
            asks_gmv=asks_gmv,
            aggregation=interpretation.metric_aggregation,
        )
        used_fields = [interpretation.metric_field, interpretation.dimension_field or ""]
    else:
        join_clause = _join_clause(profile, metric_table, dimension_table)
        metric_expr, metric_used_fields, alias = _metric_expression_for_join(
            profile,
            metric_table=metric_table,
            metric_column=metric_column,
            dimension_table=dimension_table,
            asks_gmv=asks_gmv,
            aggregation=interpretation.metric_aggregation,
        )
        dimension_expr = f"{dimension_table}.{dimension_column}"
        from_clause = join_clause
        used_fields = [*metric_used_fields, interpretation.dimension_field or ""]

    order_expr = f"{aggregate}({metric_expr})"
    query = (
        f"SELECT {dimension_expr} AS {dimension_column}, {order_expr} AS {alias} "
        f"FROM {from_clause} "
        f"GROUP BY {dimension_expr} "
        f"ORDER BY {order_expr} DESC "
        f"LIMIT {top_n}"
    )
    return query, [field for field in used_fields if field]


def _draft_sql_with_llm(
    state: AgentState,
    *,
    data_source: DataSource,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> AgentState:
    """Draft SQL from a narrow JSON LLM response and keep guard metadata."""

    interpretation = _require_interpretation(state)
    profile_payload = (
        state.database_profile.model_dump(mode="json")
        if state.database_profile is not None
        else None
    )
    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="sql_drafter",
        prompt_loader=prompt_loader,
        state=state,
        node_name="draft_sql",
        user_payload={
            "question_interpretation": interpretation.model_dump(mode="json"),
            "database_profile": profile_payload,
            "available_schema": _profile_constraints(state.database_profile),
            "previous_analysis_summary": _previous_analysis_summary(state),
            "is_followup_correction": state.is_followup_correction,
            "dialect": data_source.dialect,
        },
    )
    query = payload["query"]
    guard_result = validate_select_only_sql(query, dialect=data_source.dialect)
    used_tables = _string_list(payload.get("used_tables")) or guard_result.referenced_tables
    used_fields = _string_list(payload.get("used_fields")) or _infer_used_fields_from_sql(
        query,
        dialect=data_source.dialect,
        profile=state.database_profile,
    )
    state.sql_draft = SqlDraft(
        query=query,
        dialect=_sql_dialect(data_source.dialect),
        rationale=payload.get("reason") or payload.get("rationale", "LLM-drafted SQL."),
        referenced_tables=guard_result.referenced_tables,
        referenced_columns=guard_result.referenced_columns,
        used_tables=used_tables,
        used_fields=used_fields,
        generation_strategy="llm",
    )
    return state


def validate_sql(state: AgentState, *, data_source: DataSource) -> AgentState:
    """Validate SQL safety, referenced schema fields, and LLM-declared fields."""

    sql_draft = _require_sql_draft(state)
    guard_result = validate_select_only_sql(sql_draft.query, dialect=data_source.dialect)
    errors = list(guard_result.errors)
    warnings = list(guard_result.warnings)

    for table_name in guard_result.referenced_tables:
        if not data_source.has_table(table_name):
            errors.append(f"Unknown table referenced by SQL: {table_name}")

    for column_name in guard_result.referenced_columns:
        if guard_result.referenced_tables and not any(
            data_source.has_column(table_name, column_name)
            for table_name in guard_result.referenced_tables
        ):
            errors.append(f"Unknown column referenced by SQL: {column_name}")

    for table_name in sql_draft.used_tables:
        if not data_source.has_table(table_name):
            errors.append(f"Unknown table declared by SQL drafter: {table_name}")

    for field in sql_draft.used_fields:
        table_name, column_name = _parse_qualified_field(field)
        if table_name is None or column_name is None:
            errors.append(f"SQL drafter used field must be qualified as table.column: {field}")
        elif not data_source.has_table(table_name):
            errors.append(f"Unknown field declared by SQL drafter: {field} (table does not exist)")
        elif not data_source.has_column(table_name, column_name):
            errors.append(f"Unknown field declared by SQL drafter: {field}")

    for field in _qualified_columns_from_sql(sql_draft.query, dialect=data_source.dialect):
        table_name, column_name = _split_qualified_field(field)
        if not data_source.has_table(table_name):
            errors.append(f"Unknown table referenced by qualified field: {table_name}")
        elif not data_source.has_column(table_name, column_name):
            errors.append(f"Unknown qualified field referenced by SQL: {field}")

    errors = _dedupe(errors)
    is_valid = guard_result.is_allowed and not errors
    state.sql_validation = SqlValidation(
        status=SqlValidationStatus.VALID if is_valid else SqlValidationStatus.INVALID,
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        estimated_rows=None,
        estimated_seconds=None,
    )
    return state


def risk_check_sql(state: AgentState) -> AgentState:
    """Apply minimal risk checks without executing SQL or requesting export."""

    if state.sql_validation is None:
        raise ValueError("SqlValidation is required before risk check.")
    if state.sql_draft is None:
        raise ValueError("SqlDraft is required before risk check.")
    if not state.sql_validation.is_valid:
        return state

    warnings = list(state.sql_validation.warnings)
    query_upper = state.sql_draft.query.upper()
    if "SELECT *" in query_upper:
        warnings.append("SELECT * queries may return too many columns.")
    state.sql_validation = state.sql_validation.model_copy(update={"warnings": warnings})
    return state


def _profile_constraints(profile: DatabaseProfile | None) -> dict[str, object] | None:
    """Return a compact schema contract for the SQL drafter prompt."""

    if profile is None:
        return None
    return {
        "tables": [
            {
                "name": table.name,
                "role": table.role.value,
                "columns": [
                    {
                        "field": f"{table.name}.{column.name}",
                        "data_type": column.data_type,
                        "semantic_type": column.semantic_type.value,
                        "is_metric_candidate": column.is_metric_candidate,
                        "is_dimension_candidate": column.is_dimension_candidate,
                    }
                    for column in table.columns
                ],
            }
            for table in profile.tables
        ],
        "relationships": [
            relationship.model_dump(mode="json") for relationship in profile.relationships
        ],
        "time_fields": profile.time_fields,
        "candidate_metrics": profile.candidate_metrics,
        "candidate_dimensions": profile.candidate_dimensions,
    }


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


def _require_interpretation(state: AgentState) -> QuestionInterpretation:
    if state.question_interpretation is None:
        raise ValueError("QuestionInterpretation is required before SQL drafting.")
    return state.question_interpretation


def _require_sql_draft(state: AgentState) -> SqlDraft:
    if state.sql_draft is None:
        raise ValueError("SqlDraft is required before SQL validation.")
    return state.sql_draft


def _require_profile(state: AgentState) -> DatabaseProfile:
    if state.database_profile is None:
        raise ValueError("DatabaseProfile is required before SQL drafting.")
    return state.database_profile


def _sql_dialect(dialect: str) -> SqlDialect:
    try:
        return SqlDialect(dialect)
    except ValueError:
        return SqlDialect.UNKNOWN


def _split_qualified_field(field: str) -> tuple[str, str]:
    table_name, column_name = field.split(".", maxsplit=1)
    return table_name, column_name


def _parse_qualified_field(field: str) -> tuple[str | None, str | None]:
    if "." not in field:
        return None, None
    return _split_qualified_field(field)


def _asks_for_gmv(question: str) -> bool:
    question_lower = question.lower()
    return any(token in question_lower for token in GMV_TOKENS)


def _aggregate_function(metric_aggregation: str) -> str:
    return "AVG" if metric_aggregation == "avg" else "SUM"


def _aggregate_alias(metric_column: str, metric_aggregation: str) -> str:
    prefix = "avg" if metric_aggregation == "avg" else "total"
    return f"{prefix}_{metric_column}"


def _metric_alias(metric_column: str, *, asks_gmv: bool, aggregation: str) -> str:
    if aggregation == "avg":
        return f"avg_{metric_column}"
    return "total_gmv" if asks_gmv else f"total_{metric_column}"


def _metric_expression_for_join(
    profile: DatabaseProfile,
    *,
    metric_table: str,
    metric_column: str,
    dimension_table: str,
    asks_gmv: bool,
    aggregation: str,
) -> tuple[str, list[str], str]:
    metric_field = f"{metric_table}.{metric_column}"
    if asks_gmv and metric_column in QUANTITY_COLUMNS:
        price_field = _first_existing_field(profile, dimension_table, PRICE_COLUMNS)
        if price_field is not None:
            _, price_column = _split_qualified_field(price_field)
            return (
                f"{metric_table}.{metric_column} * {dimension_table}.{price_column}",
                [metric_field, price_field],
                "avg_unit_price" if aggregation == "avg" else "total_gmv",
            )
    return (
        f"{metric_table}.{metric_column}",
        [metric_field],
        _metric_alias(
            metric_column,
            asks_gmv=asks_gmv,
            aggregation=aggregation,
        ),
    )


def _join_clause(profile: DatabaseProfile, left_table: str, right_table: str) -> str:
    if left_table == right_table:
        return left_table
    for relationship in profile.relationships:
        if relationship.from_table == left_table and relationship.to_table == right_table:
            left_key = f"{left_table}.{relationship.from_column}"
            right_key = f"{right_table}.{relationship.to_column}"
            return f"{left_table} JOIN {right_table} ON {left_key} = {right_key}"
        if relationship.to_table == left_table and relationship.from_table == right_table:
            left_key = f"{left_table}.{relationship.to_column}"
            right_key = f"{right_table}.{relationship.from_column}"
            return f"{left_table} JOIN {right_table} ON {left_key} = {right_key}"
    raise ValueError(f"No profiled relationship joins {left_table} to {right_table}.")


def _first_existing_field(
    profile: DatabaseProfile,
    table_name: str,
    candidate_columns: tuple[str, ...],
) -> str | None:
    for table in profile.tables:
        if table.name != table_name:
            continue
        for column_name in candidate_columns:
            if any(column.name == column_name for column in table.columns):
                return f"{table_name}.{column_name}"
    return None


def _qualified_columns_from_sql(sql: str, *, dialect: str | None) -> list[str]:
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except ParseError:
        return []
    fields: list[str] = []
    for column in parsed.find_all(exp.Column):
        if column.table and column.name:
            fields.append(f"{column.table}.{column.name}")
    return _dedupe(fields)


def _infer_used_fields_from_sql(
    sql: str,
    *,
    dialect: str | None,
    profile: DatabaseProfile | None,
) -> list[str]:
    qualified = _qualified_columns_from_sql(sql, dialect=dialect)
    if qualified or profile is None:
        return qualified
    guard_result = validate_select_only_sql(sql, dialect=dialect)
    inferred: list[str] = []
    for column_name in guard_result.referenced_columns:
        matches = [
            f"{table.name}.{column.name}"
            for table in profile.tables
            for column in table.columns
            if column.name == column_name and table.name in guard_result.referenced_tables
        ]
        if len(matches) == 1:
            inferred.append(matches[0])
    return _dedupe(inferred)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
