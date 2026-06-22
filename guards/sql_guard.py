"""SQL safety guard that parses statements without executing them."""

from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from pydantic import Field
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

from schemas._base import StrictBaseModel

FORBIDDEN_SQL_KEYWORDS: tuple[str, ...] = (
    "UPDATE",
    "DELETE",
    "INSERT",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
)


class SqlGuardResult(StrictBaseModel):
    """Result of SQL guard validation before any execution tool can run."""

    sql: str
    is_allowed: bool
    statement_type: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    common_table_expressions: list[str] = Field(default_factory=list)


def _forbidden_expression_types() -> tuple[type[exp.Expression], ...]:
    """Return sqlglot expression classes that represent write or DDL statements."""

    class_names = (
        "Alter",
        "Command",
        "Create",
        "Delete",
        "Drop",
        "Grant",
        "Insert",
        "Merge",
        "Revoke",
        "Truncate",
        "Update",
    )
    return tuple(
        expression_type
        for class_name in class_names
        if isinstance(expression_type := getattr(exp, class_name, None), type)
    )


def _collect_names(expressions: Iterable[exp.Expression]) -> list[str]:
    """Collect unique sqlglot expression names while preserving first-seen order."""

    names: list[str] = []
    seen: set[str] = set()
    for expression in expressions:
        name = expression.name
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _collect_cte_names(expressions: Iterable[exp.CTE]) -> list[str]:
    """Collect CTE aliases while preserving first-seen order."""

    names: list[str] = []
    seen: set[str] = set()
    for expression in expressions:
        name = expression.alias_or_name
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def validate_select_only_sql(sql: str, dialect: str | None = None) -> SqlGuardResult:
    """Validate that SQL is a single SELECT or WITH SELECT statement."""

    stripped_sql = sql.strip()
    if not stripped_sql:
        return SqlGuardResult(sql=sql, is_allowed=False, errors=["SQL is empty."])

    try:
        parsed_statements = sqlglot.parse(stripped_sql, read=dialect)
    except ParseError as exc:
        return SqlGuardResult(
            sql=sql,
            is_allowed=False,
            errors=[f"SQL parse failed: {exc}"],
        )

    if len(parsed_statements) != 1:
        return SqlGuardResult(
            sql=sql,
            is_allowed=False,
            errors=["Only one SQL statement is allowed."],
        )

    expression = parsed_statements[0]
    statement_type = expression.key.upper() if expression.key else type(expression).__name__.upper()

    if not isinstance(expression, exp.Select):
        return SqlGuardResult(
            sql=sql,
            is_allowed=False,
            statement_type=statement_type,
            errors=["Only SELECT or WITH SELECT statements are allowed."],
        )

    forbidden_types = _forbidden_expression_types()
    forbidden_nodes = list(expression.find_all(*forbidden_types)) if forbidden_types else []
    if forbidden_nodes:
        found_types = sorted({node.key.upper() for node in forbidden_nodes if node.key})
        return SqlGuardResult(
            sql=sql,
            is_allowed=False,
            statement_type=statement_type,
            errors=[f"Forbidden SQL operation detected: {', '.join(found_types)}."],
        )

    common_table_expressions = _collect_cte_names(expression.find_all(exp.CTE))
    physical_tables = [
        table_name
        for table_name in _collect_names(expression.find_all(exp.Table))
        if table_name not in common_table_expressions
    ]

    return SqlGuardResult(
        sql=sql,
        is_allowed=True,
        statement_type=statement_type,
        referenced_tables=physical_tables,
        referenced_columns=_collect_names(expression.find_all(exp.Column)),
        common_table_expressions=common_table_expressions,
    )
