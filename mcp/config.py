"""MCP server 与 tool 的配置 schema。"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator

from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from schemas._base import StrictBaseModel

ALLOWED_STDIO_COMMANDS: frozenset[str] = frozenset(
    {
        "uvx",
        "uv",
        "npx",
        "node",
        "python",
        "python3",
        "deno",
    }
)
SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
RAW_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class MCPServerConfig(StrictBaseModel):
    """单个 MCP server 的静态配置，不负责启动真实进程。"""

    server_id: str
    transport: Literal["stdio", "sse", "fake"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("server_id")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        """校验 server_id，避免破坏 mcp__server__tool 命名空间。"""

        return validate_server_id(value)

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str | None) -> str | None:
        """校验 stdio command 白名单。"""

        if value is None:
            return value
        return validate_stdio_command(value)


class MCPToolConfig(StrictBaseModel):
    """单个 MCP tool 的注册配置。"""

    server_id: str
    raw_tool_name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_nodes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("server_id")
    @classmethod
    def validate_tool_server_id(cls, value: str) -> str:
        """复用 server_id 校验，确保工具名可组合。"""

        return validate_server_id(value)

    @field_validator("raw_tool_name")
    @classmethod
    def validate_raw_tool_name(cls, value: str) -> str:
        """校验 raw tool name，禁止嵌入双下划线分隔符。"""

        return validate_raw_tool_name(value)

    @property
    def registry_name(self) -> str:
        """返回 ToolRegistry 使用的 MCP namespaced tool 名。"""

        return f"mcp__{self.server_id}__{self.raw_tool_name}"


def validate_server_id(server_id: str) -> str:
    """校验 MCP server_id。"""

    if not server_id or "__" in server_id or not SERVER_ID_PATTERN.fullmatch(server_id):
        raise MCPAdapterError(
            MCPErrorDetail(
                code=MCPErrorCode.INVALID_SERVER_ID,
                message=f"Invalid MCP server_id: {server_id}",
                details={"server_id": server_id},
            )
        )
    return server_id


def validate_raw_tool_name(raw_tool_name: str) -> str:
    """校验 MCP raw tool name。"""

    if (
        not raw_tool_name
        or "__" in raw_tool_name
        or not RAW_TOOL_NAME_PATTERN.fullmatch(raw_tool_name)
    ):
        raise MCPAdapterError(
            MCPErrorDetail(
                code=MCPErrorCode.INVALID_TOOL_NAME,
                message=f"Invalid MCP raw tool name: {raw_tool_name}",
                details={"raw_tool_name": raw_tool_name},
            )
        )
    return raw_tool_name


def validate_stdio_command(command: str) -> str:
    """校验 stdio transport command 是否在白名单内。"""

    command_name = command.strip()
    if command_name not in ALLOWED_STDIO_COMMANDS:
        raise MCPAdapterError(
            MCPErrorDetail(
                code=MCPErrorCode.COMMAND_NOT_ALLOWED,
                message=f"MCP stdio command is not allowed: {command}",
                details={
                    "command": command,
                    "allowed_commands": sorted(ALLOWED_STDIO_COMMANDS),
                },
            )
        )
    return command_name
