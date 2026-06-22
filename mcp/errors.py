"""MCP adapter 的结构化错误模型。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel


class MCPErrorCode(StrEnum):
    """MCP skeleton 中可稳定断言的错误类型。"""

    INVALID_SERVER_ID = "invalid_server_id"
    INVALID_TOOL_NAME = "invalid_tool_name"
    COMMAND_NOT_ALLOWED = "command_not_allowed"
    SERVER_NOT_REGISTERED = "server_not_registered"
    SERVER_NOT_CONNECTED = "server_not_connected"
    TOOL_NOT_REGISTERED = "tool_not_registered"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    TRANSPORT_ERROR = "transport_error"
    PROTOCOL_ERROR = "protocol_error"
    REQUEST_TIMEOUT = "request_timeout"
    JSON_RPC_ERROR = "json_rpc_error"


class MCPErrorDetail(StrictBaseModel):
    """MCP 错误的结构化细节。"""

    code: MCPErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MCPAdapterError(Exception):
    """MCP adapter 抛出的统一异常。"""

    def __init__(self, detail: MCPErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.message)
