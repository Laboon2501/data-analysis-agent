"""Layered tool registry without node-level dispatcher logic."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from typing import Any

from datasource.base import DataSource
from tools.schema_tools import get_schema, get_table_detail, sample_table
from tools.sql_tools import query_data

ToolHandler = Callable[..., Any]

DEFAULT_NODE_TOOL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "read_schema": ("schema",),
    "sample_tables": ("schema",),
    "ensure_database_profile": ("schema",),
    "draft_sql": ("sql",),
    "validate_sql": ("sql",),
    "execute_sql": ("sql",),
}


@dataclass(frozen=True)
class ToolDefinition:
    """Registered tool metadata and callable handler."""

    name: str
    category: str
    handler: ToolHandler
    description: str | None = None


class ToolRegistry:
    """Register tools by category and expose only node-allowed categories."""

    def __init__(self) -> None:
        self._tools_by_name: dict[str, ToolDefinition] = {}
        self._tool_names_by_category: dict[str, set[str]] = defaultdict(set)
        self._node_allowed_categories: dict[str, set[str]] = defaultdict(set)
        self._node_allowed_tool_names: dict[str, set[str]] = defaultdict(set)

    def register_tool(
        self,
        *,
        name: str,
        category: str,
        handler: ToolHandler,
        description: str | None = None,
    ) -> None:
        """Register a uniquely named tool under one category."""

        if name in self._tools_by_name:
            raise ValueError(f"Tool '{name}' is already registered.")
        definition = ToolDefinition(
            name=name,
            category=category,
            handler=handler,
            description=description,
        )
        self._tools_by_name[name] = definition
        self._tool_names_by_category[category].add(name)

    def allow_categories_for_node(self, node_name: str, categories: Iterable[str]) -> None:
        """Grant a node access to every tool in the provided categories."""

        self._node_allowed_categories[node_name].update(categories)

    def allow_tools_for_node(self, node_name: str, tool_names: Iterable[str]) -> None:
        """给节点授权具体工具，避免授予整个 category。"""

        for tool_name in tool_names:
            if tool_name not in self._tools_by_name:
                raise KeyError(f"Tool '{tool_name}' is not registered.")
            self._node_allowed_tool_names[node_name].add(tool_name)

    def get_tool(self, name: str) -> ToolDefinition:
        """Return a registered tool definition by name."""

        try:
            return self._tools_by_name[name]
        except KeyError as exc:
            raise KeyError(f"Tool '{name}' is not registered.") from exc

    def get_tools_by_category(self, category: str) -> tuple[ToolDefinition, ...]:
        """Return tools registered in one category."""

        tool_names = sorted(self._tool_names_by_category.get(category, set()))
        return tuple(self._tools_by_name[tool_name] for tool_name in tool_names)

    def get_allowed_tools(self, node_name: str) -> tuple[ToolDefinition, ...]:
        """Return tools available to a node based on category grants."""

        allowed_names: set[str] = set()
        for category in self._node_allowed_categories.get(node_name, set()):
            allowed_names.update(self._tool_names_by_category.get(category, set()))
        allowed_names.update(self._node_allowed_tool_names.get(node_name, set()))
        return tuple(self._tools_by_name[tool_name] for tool_name in sorted(allowed_names))

    def get_allowed_handlers(self, node_name: str) -> dict[str, ToolHandler]:
        """Return node-allowed callables keyed by tool name."""

        return {
            definition.name: definition.handler for definition in self.get_allowed_tools(node_name)
        }


def register_datasource_tools(
    registry: ToolRegistry,
    data_source: DataSource,
    node_tool_categories: dict[str, tuple[str, ...]] | None = None,
) -> ToolRegistry:
    """Register datasource-backed schema and SQL tools in a layered registry."""

    registry.register_tool(
        name="get_schema",
        category="schema",
        handler=partial(get_schema, data_source),
        description="Return datasource schema metadata.",
    )
    registry.register_tool(
        name="get_table_detail",
        category="schema",
        handler=partial(get_table_detail, data_source),
        description="Return detailed metadata for one table.",
    )
    registry.register_tool(
        name="sample_table",
        category="schema",
        handler=partial(sample_table, data_source),
        description="Return bounded sample rows for one table.",
    )
    registry.register_tool(
        name="query_data",
        category="sql",
        handler=partial(query_data, data_source),
        description="Run guarded read-only SQL and return a QueryResult.",
    )

    for node_name, categories in (node_tool_categories or DEFAULT_NODE_TOOL_CATEGORIES).items():
        registry.allow_categories_for_node(node_name, categories)

    return registry


def build_datasource_tool_registry(
    data_source: DataSource,
    node_tool_categories: dict[str, tuple[str, ...]] | None = None,
) -> ToolRegistry:
    """Build a registry with datasource-backed tools and node permissions."""

    return register_datasource_tools(
        ToolRegistry(),
        data_source,
        node_tool_categories=node_tool_categories,
    )
