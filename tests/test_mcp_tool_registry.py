"""MCP tools 与 ToolRegistry 集成测试。"""

from typing import Any

import pytest

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner
from mcp.adapter import register_mcp_tools
from mcp.config import MCPServerConfig, MCPToolConfig
from mcp.errors import MCPAdapterError, MCPErrorCode
from mcp.manager import MCPManager
from schemas import AgentCommand, AgentIntent
from tools.registry import ToolRegistry


class FakeMCPTransport:
    """ToolRegistry 集成测试使用的 fake transport。"""

    def __init__(self, tools: list[MCPToolConfig]) -> None:
        self.tools = tools

    def connect(self, server_config: MCPServerConfig) -> None:
        """fake connect 不启动任何进程。"""

    def disconnect(self, server_id: str) -> None:
        """fake disconnect 不执行外部操作。"""

    def list_tools(self, server_id: str) -> list[MCPToolConfig]:
        """返回指定 server 的 fake tools。"""

        return [tool for tool in self.tools if tool.server_id == server_id]

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """返回 fake MCP 调用结果。"""

        return {
            "server_id": server_id,
            "raw_tool_name": raw_tool_name,
            "arguments": arguments or {},
        }


def test_register_mcp_tools_uses_mcp_category_and_node_tool_grants() -> None:
    """MCP tools 应注册到 mcp category，但只暴露给 allowed_nodes。"""

    manager = _manager_with_tools(
        [
            MCPToolConfig(
                server_id="analytics",
                raw_tool_name="schema.read",
                allowed_nodes=["read_schema"],
            ),
            MCPToolConfig(
                server_id="analytics",
                raw_tool_name="chart.render",
                allowed_nodes=["generate_chart_artifact"],
            ),
        ]
    )
    registry = register_mcp_tools(ToolRegistry(), manager)

    assert [tool.name for tool in registry.get_tools_by_category("mcp")] == [
        "mcp__analytics__chart.render",
        "mcp__analytics__schema.read",
    ]
    assert [tool.name for tool in registry.get_allowed_tools("read_schema")] == [
        "mcp__analytics__schema.read"
    ]
    assert [tool.name for tool in registry.get_allowed_tools("generate_chart_artifact")] == [
        "mcp__analytics__chart.render"
    ]
    assert registry.get_allowed_tools("llm_router") == ()


def test_demo_mcp_tools_stay_node_scoped() -> None:
    """demo MCP tools 注册到 mcp category，但不会自动暴露给 LLM 节点。"""

    manager = _manager_with_tools(
        [
            MCPToolConfig(
                server_id="demo_mcp",
                raw_tool_name="list_demo_tables",
                allowed_nodes=["read_schema"],
            ),
            MCPToolConfig(
                server_id="demo_mcp",
                raw_tool_name="describe_demo_table",
                allowed_nodes=["read_schema"],
            ),
        ],
        server_id="demo_mcp",
    )
    registry = register_mcp_tools(ToolRegistry(), manager)

    assert [tool.name for tool in registry.get_tools_by_category("mcp")] == [
        "mcp__demo_mcp__describe_demo_table",
        "mcp__demo_mcp__list_demo_tables",
    ]
    assert [tool.name for tool in registry.get_allowed_tools("read_schema")] == [
        "mcp__demo_mcp__describe_demo_table",
        "mcp__demo_mcp__list_demo_tables",
    ]
    assert registry.get_allowed_tools("llm_router") == ()
    assert registry.get_allowed_handlers("llm_router") == {}


def test_mcp_tool_handler_stays_behind_registry_permissions() -> None:
    """未授权节点拿不到 handler，授权节点才能间接调用 MCP tool。"""

    manager = _manager_with_tools(
        [
            MCPToolConfig(
                server_id="analytics",
                raw_tool_name="schema.read",
                allowed_nodes=["read_schema"],
            )
        ]
    )
    registry = register_mcp_tools(ToolRegistry(), manager)

    assert registry.get_allowed_handlers("draft_sql") == {}
    handlers = registry.get_allowed_handlers("read_schema")

    assert handlers["mcp__analytics__schema.read"](table="orders") == {
        "server_id": "analytics",
        "raw_tool_name": "schema.read",
        "arguments": {"table": "orders"},
    }


def test_demo_mcp_invalid_server_or_tool_names_are_rejected() -> None:
    """非法 server_id 或 raw tool name 不能进入 mcp__server__tool 命名空间。"""

    with pytest.raises(MCPAdapterError) as server_exc:
        MCPToolConfig(server_id="bad__server", raw_tool_name="list_demo_tables")
    with pytest.raises(MCPAdapterError) as tool_exc:
        MCPToolConfig(server_id="demo_mcp", raw_tool_name="bad__tool")

    assert server_exc.value.detail.code is MCPErrorCode.INVALID_SERVER_ID
    assert tool_exc.value.detail.code is MCPErrorCode.INVALID_TOOL_NAME


def test_harness_and_runner_accept_optional_mcp_manager() -> None:
    """harness 和 worker 可注入 MCPManager，但默认不启用 MCP 流程。"""

    manager = _manager_with_tools([])
    state = build_initial_state(
        session_id="session-1",
        user_message="export report",
        command=AgentCommand.REPORT,
        mcp_manager=manager,
    )
    runner = InMemoryJobRunner(mcp_manager=manager)

    assert state.intent is AgentIntent.REPORT_EXPORT
    assert runner.mcp_manager is manager


def _manager_with_tools(
    tools: list[MCPToolConfig],
    *,
    server_id: str = "analytics",
) -> MCPManager:
    """构造已连接的 fake MCP manager。"""

    manager = MCPManager()
    manager.register_server(
        MCPServerConfig(server_id=server_id, transport="fake"),
        transport=FakeMCPTransport(tools),
    )
    manager.connect(server_id)
    return manager
