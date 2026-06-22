"""Tests for layered tool registration and node-scoped access."""

import pytest

from tools.registry import ToolRegistry


def _sample_tool() -> str:
    return "ok"


def test_registry_returns_tools_by_category_and_node_grants() -> None:
    """Nodes should only receive tools from categories explicitly granted to them."""

    registry = ToolRegistry()
    registry.register_tool(name="read_schema", category="schema", handler=_sample_tool)
    registry.register_tool(name="execute_sql", category="sql", handler=_sample_tool)
    registry.allow_categories_for_node("context_node", ["schema"])

    allowed = registry.get_allowed_tools("context_node")

    assert [tool.name for tool in allowed] == ["read_schema"]
    assert registry.get_allowed_handlers("context_node") == {"read_schema": _sample_tool}
    assert [tool.name for tool in registry.get_tools_by_category("sql")] == ["execute_sql"]


def test_registry_rejects_duplicate_tool_names() -> None:
    """Tool names should be globally unique."""

    registry = ToolRegistry()
    registry.register_tool(name="read_schema", category="schema", handler=_sample_tool)

    with pytest.raises(ValueError):
        registry.register_tool(name="read_schema", category="profile", handler=_sample_tool)


def test_ungranted_node_gets_no_tools() -> None:
    """A node without category grants should not see registered tools."""

    registry = ToolRegistry()
    registry.register_tool(name="execute_sql", category="sql", handler=_sample_tool)

    assert registry.get_allowed_tools("insight_node") == ()
