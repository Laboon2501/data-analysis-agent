"""MCP tool 到 ToolRegistry 的适配层。"""

from __future__ import annotations

from functools import partial
from typing import Any

from mcp.config import MCPToolConfig, validate_raw_tool_name, validate_server_id
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from mcp.manager import MCPManager
from tools.registry import ToolDefinition, ToolRegistry

MCP_TOOL_PREFIX = "mcp"


def mcp_tool_name(server_id: str, raw_tool_name: str) -> str:
    """生成符合 mcp__server__tool 规则的 ToolRegistry 工具名。"""

    safe_server_id = validate_server_id(server_id)
    safe_tool_name = validate_raw_tool_name(raw_tool_name)
    return f"{MCP_TOOL_PREFIX}__{safe_server_id}__{safe_tool_name}"


def parse_mcp_tool_name(tool_name: str) -> tuple[str, str]:
    """解析并校验 mcp__server__tool 工具名。"""

    parts = tool_name.split("__")
    if len(parts) != 3 or parts[0] != MCP_TOOL_PREFIX:
        raise MCPAdapterError(
            MCPErrorDetail(
                code=MCPErrorCode.INVALID_TOOL_NAME,
                message=f"Invalid MCP registry tool name: {tool_name}",
                details={"tool_name": tool_name},
            )
        )
    return validate_server_id(parts[1]), validate_raw_tool_name(parts[2])


def adapt_mcp_tool(manager: MCPManager, tool_config: MCPToolConfig) -> ToolDefinition:
    """把单个 MCP tool 配置转换为 ToolRegistry 定义。"""

    return ToolDefinition(
        name=mcp_tool_name(tool_config.server_id, tool_config.raw_tool_name),
        category="mcp",
        handler=partial(
            _call_mcp_tool,
            manager,
            tool_config.server_id,
            tool_config.raw_tool_name,
        ),
        description=tool_config.description,
    )


def register_mcp_tools(
    registry: ToolRegistry,
    manager: MCPManager,
    *,
    tools: list[MCPToolConfig] | None = None,
) -> ToolRegistry:
    """把 MCP tools 注册到 registry 的 mcp category，并按节点显式授权。"""

    active_tools = tools if tools is not None else list(manager.list_tools())
    for tool_config in active_tools:
        definition = adapt_mcp_tool(manager, tool_config)
        registry.register_tool(
            name=definition.name,
            category=definition.category,
            handler=definition.handler,
            description=definition.description,
        )
        for node_name in tool_config.allowed_nodes:
            registry.allow_tools_for_node(node_name, [definition.name])
    return registry


def _call_mcp_tool(
    manager: MCPManager,
    server_id: str,
    raw_tool_name: str,
    **arguments: Any,
) -> Any:
    """调用 manager 管理的 MCP tool，不绕过 manager 的状态检查。"""

    return manager.call_tool(server_id, raw_tool_name, arguments)
