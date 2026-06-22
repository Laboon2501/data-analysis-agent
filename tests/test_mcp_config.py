"""MCP 配置 schema 测试。"""

import pytest

from mcp.config import MCPServerConfig, MCPToolConfig
from mcp.errors import MCPAdapterError, MCPErrorCode


def test_mcp_server_config_accepts_allowed_stdio_command() -> None:
    """stdio command 在白名单内时应允许配置。"""

    config = MCPServerConfig(server_id="analytics", command="python")

    assert config.server_id == "analytics"
    assert config.command == "python"
    assert config.transport == "stdio"


def test_mcp_server_config_rejects_invalid_server_id() -> None:
    """server_id 不能包含分隔符或非法字符。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        MCPServerConfig(server_id="bad__server", command="python")

    assert exc_info.value.detail.code is MCPErrorCode.INVALID_SERVER_ID


def test_mcp_tool_config_builds_registry_name() -> None:
    """MCPToolConfig 应生成稳定的 mcp__server__tool 名称。"""

    tool = MCPToolConfig(
        server_id="analytics",
        raw_tool_name="profile.read",
        allowed_nodes=["read_schema"],
    )

    assert tool.registry_name == "mcp__analytics__profile.read"
    assert tool.allowed_nodes == ["read_schema"]


def test_mcp_tool_config_rejects_invalid_raw_tool_name() -> None:
    """raw_tool_name 不能破坏 mcp 命名空间。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        MCPToolConfig(server_id="analytics", raw_tool_name="bad__tool")

    assert exc_info.value.detail.code is MCPErrorCode.INVALID_TOOL_NAME
