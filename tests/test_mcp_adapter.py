"""MCP adapter 测试。"""

from typing import Any

import pytest

from mcp.adapter import adapt_mcp_tool, mcp_tool_name, parse_mcp_tool_name
from mcp.config import MCPServerConfig, MCPToolConfig
from mcp.errors import MCPAdapterError, MCPErrorCode
from mcp.manager import MCPManager


class FakeMCPTransport:
    """不启动外部进程的 fake MCP transport。"""

    def __init__(self, tools: list[MCPToolConfig]) -> None:
        self.tools = tools
        self.connected_servers: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def connect(self, server_config: MCPServerConfig) -> None:
        """记录连接，不启动真实 MCP server。"""

        self.connected_servers.append(server_config.server_id)

    def disconnect(self, server_id: str) -> None:
        """记录断开。"""

        self.connected_servers.remove(server_id)

    def list_tools(self, server_id: str) -> list[MCPToolConfig]:
        """返回预置 fake tools。"""

        return [tool for tool in self.tools if tool.server_id == server_id]

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """返回可断言的 fake 调用结果。"""

        payload = {
            "server_id": server_id,
            "raw_tool_name": raw_tool_name,
            "arguments": arguments or {},
        }
        self.calls.append(payload)
        return payload


def test_mcp_tool_name_and_parse_round_trip() -> None:
    """MCP registry tool name 应能稳定生成并解析。"""

    tool_name = mcp_tool_name("analytics", "schema.read")

    assert tool_name == "mcp__analytics__schema.read"
    assert parse_mcp_tool_name(tool_name) == ("analytics", "schema.read")


def test_parse_mcp_tool_name_rejects_invalid_name() -> None:
    """不符合 mcp__server__tool 的名称应被拒绝。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        parse_mcp_tool_name("schema.read")

    assert exc_info.value.detail.code is MCPErrorCode.INVALID_TOOL_NAME


def test_adapt_mcp_tool_calls_manager_transport() -> None:
    """适配后的 ToolDefinition handler 应通过 MCPManager 调用 fake transport。"""

    tool = MCPToolConfig(
        server_id="analytics",
        raw_tool_name="schema.read",
        description="Read schema through MCP.",
    )
    transport = FakeMCPTransport([tool])
    manager = MCPManager()
    manager.register_server(
        MCPServerConfig(server_id="analytics", transport="fake"),
        transport=transport,
    )
    manager.connect("analytics")

    definition = adapt_mcp_tool(manager, tool)
    result = definition.handler(table="orders")

    assert definition.name == "mcp__analytics__schema.read"
    assert definition.category == "mcp"
    assert result == {
        "server_id": "analytics",
        "raw_tool_name": "schema.read",
        "arguments": {"table": "orders"},
    }
    assert transport.calls == [result]
