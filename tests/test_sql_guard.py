"""Tests for SQL safety guard parsing and write-operation rejection."""

import pytest

from guards.sql_guard import validate_select_only_sql


def test_select_statement_is_allowed_and_references_are_collected() -> None:
    """A single SELECT should pass without executing anything."""

    result = validate_select_only_sql("SELECT created_at, revenue FROM orders")

    assert result.is_allowed is True
    assert result.statement_type == "SELECT"
    assert result.referenced_tables == ["orders"]
    assert result.referenced_columns == ["created_at", "revenue"]


def test_with_select_statement_is_allowed() -> None:
    """WITH SELECT should be treated as a select-only query."""

    result = validate_select_only_sql(
        "WITH monthly AS (SELECT month, revenue FROM orders) SELECT month FROM monthly"
    )

    assert result.is_allowed is True
    assert result.statement_type == "SELECT"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE orders SET revenue = 0",
        "DELETE FROM orders",
        "INSERT INTO orders VALUES (1)",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN x INT",
        "TRUNCATE TABLE orders",
        "CREATE TABLE orders_copy AS SELECT * FROM orders",
        "GRANT SELECT ON orders TO analyst",
        "REVOKE SELECT ON orders FROM analyst",
    ],
)
def test_write_and_ddl_statements_are_rejected(sql: str) -> None:
    """Non-SELECT statements must be rejected by the guard."""

    result = validate_select_only_sql(sql)

    assert result.is_allowed is False
    assert result.errors


def test_multiple_statements_are_rejected() -> None:
    """A SELECT followed by a write statement must not pass as safe."""

    result = validate_select_only_sql("SELECT * FROM orders; DROP TABLE orders")

    assert result.is_allowed is False
    assert "Only one SQL statement is allowed." in result.errors


def test_invalid_sql_is_rejected() -> None:
    """Parser errors should become structured guard errors."""

    result = validate_select_only_sql("SELECT FROM")

    assert result.is_allowed is False
    assert result.errors
