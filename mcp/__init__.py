"""MCP adapter skeleton package."""

from mcp.adapter import (
    adapt_mcp_tool,
    mcp_tool_name,
    parse_mcp_tool_name,
    register_mcp_tools,
)
from mcp.config import ALLOWED_STDIO_COMMANDS, MCPServerConfig, MCPToolConfig
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from mcp.manager import MCPConnectionStatus, MCPManager
from mcp.transport import (
    MCPSSETransport,
    MCPStdioTransport,
    MCPTransport,
    build_mcp_transport,
    tool_configs_from_mcp_tools,
)

__all__ = [
    "ALLOWED_STDIO_COMMANDS",
    "MCPAdapterError",
    "MCPConnectionStatus",
    "MCPErrorCode",
    "MCPErrorDetail",
    "MCPManager",
    "MCPServerConfig",
    "MCPSSETransport",
    "MCPStdioTransport",
    "MCPToolConfig",
    "MCPTransport",
    "adapt_mcp_tool",
    "build_mcp_transport",
    "mcp_tool_name",
    "parse_mcp_tool_name",
    "register_mcp_tools",
    "tool_configs_from_mcp_tools",
]
