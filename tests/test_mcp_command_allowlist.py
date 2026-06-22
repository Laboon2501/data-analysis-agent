"""MCP stdio command 白名单测试。"""

import pytest

from mcp.config import ALLOWED_STDIO_COMMANDS, MCPServerConfig, validate_stdio_command
from mcp.errors import MCPAdapterError, MCPErrorCode


def test_allowed_stdio_commands_are_accepted() -> None:
    """AGENTS.md 允许的 stdio command 应全部通过校验。"""

    for command in ALLOWED_STDIO_COMMANDS:
        assert validate_stdio_command(command) == command
        assert MCPServerConfig(server_id=f"server_{command}", command=command).command == command


def test_disallowed_stdio_command_is_rejected() -> None:
    """白名单外 command 不能进入 MCP server 配置。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        MCPServerConfig(server_id="unsafe", command="bash")

    assert exc_info.value.detail.code is MCPErrorCode.COMMAND_NOT_ALLOWED
    assert "python" in exc_info.value.detail.details["allowed_commands"]
