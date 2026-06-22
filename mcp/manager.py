"""MCP server 管理层，默认不自动连接任何外部服务。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from mcp.config import MCPServerConfig, MCPToolConfig
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from mcp.transport import MCPTransport


class MCPConnectionStatus(StrEnum):
    """MCP server 连接状态。"""

    REGISTERED = "registered"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class MCPManager:
    """管理 MCP server 注册、连接状态和工具列表。"""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._statuses: dict[str, MCPConnectionStatus] = {}
        self._tools_by_server: dict[str, dict[str, MCPToolConfig]] = {}
        self._transports_by_server: dict[str, MCPTransport] = {}

    def register_server(
        self,
        server_config: MCPServerConfig,
        *,
        tools: list[MCPToolConfig] | None = None,
        transport: MCPTransport | None = None,
    ) -> None:
        """注册一个 MCP server 和可选静态工具列表。"""

        self._servers[server_config.server_id] = server_config
        self._statuses[server_config.server_id] = MCPConnectionStatus.REGISTERED
        self._tools_by_server[server_config.server_id] = {}
        if transport is not None:
            self._transports_by_server[server_config.server_id] = transport
        for tool_config in tools or []:
            self.register_tool(tool_config)

    def register_tool(self, tool_config: MCPToolConfig) -> None:
        """给已注册 server 增加一个 MCP tool 配置。"""

        self._require_server(tool_config.server_id)
        self._tools_by_server.setdefault(tool_config.server_id, {})[tool_config.raw_tool_name] = (
            tool_config
        )

    def connect(self, server_id: str) -> MCPConnectionStatus:
        """连接已注册 server，并通过 transport 拉取 tools/list。"""

        server_config = self._require_server(server_id)
        transport = self._transports_by_server.get(server_id)
        if transport is None:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.TRANSPORT_UNAVAILABLE,
                    message=f"MCP transport is unavailable for server: {server_id}",
                    details={"server_id": server_id},
                )
            )
        try:
            transport.connect(server_config)
            for tool_config in transport.list_tools(server_id):
                self.register_tool(tool_config)
        except MCPAdapterError:
            self._statuses[server_id] = MCPConnectionStatus.DISCONNECTED
            raise
        except Exception as exc:
            self._statuses[server_id] = MCPConnectionStatus.DISCONNECTED
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.TRANSPORT_ERROR,
                    message=f"MCP transport failed while connecting server: {server_id}",
                    details={"server_id": server_id, "error": str(exc)},
                )
            ) from exc
        self._statuses[server_id] = MCPConnectionStatus.CONNECTED
        return self._statuses[server_id]

    def disconnect(self, server_id: str) -> MCPConnectionStatus:
        """断开 server 并更新状态。"""

        self._require_server(server_id)
        transport = self._transports_by_server.get(server_id)
        if transport is not None:
            transport.disconnect(server_id)
        self._statuses[server_id] = MCPConnectionStatus.DISCONNECTED
        return self._statuses[server_id]

    def connection_status(self, server_id: str) -> MCPConnectionStatus:
        """返回 server 当前连接状态。"""

        self._require_server(server_id)
        return self._statuses[server_id]

    def list_servers(self) -> tuple[MCPServerConfig, ...]:
        """返回已注册 server 配置。"""

        return tuple(self._servers[server_id] for server_id in sorted(self._servers))

    def list_tools(self, server_id: str | None = None) -> tuple[MCPToolConfig, ...]:
        """列出一个或全部 server 的工具配置。"""

        if server_id is not None:
            self._require_server(server_id)
            tools_by_name = self._tools_by_server.get(server_id, {})
            return tuple(tools_by_name[raw_tool_name] for raw_tool_name in sorted(tools_by_name))

        tools: list[MCPToolConfig] = []
        for active_server_id in sorted(self._tools_by_server):
            tools.extend(self.list_tools(active_server_id))
        return tuple(tools)

    def get_tool(self, server_id: str, raw_tool_name: str) -> MCPToolConfig:
        """按 server_id 和 raw tool name 读取工具配置。"""

        self._require_server(server_id)
        try:
            return self._tools_by_server[server_id][raw_tool_name]
        except KeyError as exc:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.TOOL_NOT_REGISTERED,
                    message=f"MCP tool is not registered: {server_id}/{raw_tool_name}",
                    details={
                        "server_id": server_id,
                        "raw_tool_name": raw_tool_name,
                    },
                )
            ) from exc

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """通过 transport 调用工具；未连接或无 transport 时失败。"""

        self.get_tool(server_id, raw_tool_name)
        if self.connection_status(server_id) is not MCPConnectionStatus.CONNECTED:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.SERVER_NOT_CONNECTED,
                    message=f"MCP server is not connected: {server_id}",
                    details={"server_id": server_id},
                )
            )
        transport = self._transports_by_server.get(server_id)
        if transport is None:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.TRANSPORT_UNAVAILABLE,
                    message=f"MCP transport is unavailable for server: {server_id}",
                    details={"server_id": server_id},
                )
            )
        try:
            return transport.call_tool(server_id, raw_tool_name, arguments or {})
        except MCPAdapterError:
            raise
        except Exception as exc:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.TRANSPORT_ERROR,
                    message=f"MCP transport failed while calling tool: {server_id}/{raw_tool_name}",
                    details={
                        "server_id": server_id,
                        "raw_tool_name": raw_tool_name,
                        "error": str(exc),
                    },
                )
            ) from exc

    def _require_server(self, server_id: str) -> MCPServerConfig:
        """返回 server 配置；不存在时抛结构化错误。"""

        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise MCPAdapterError(
                MCPErrorDetail(
                    code=MCPErrorCode.SERVER_NOT_REGISTERED,
                    message=f"MCP server is not registered: {server_id}",
                    details={"server_id": server_id},
                )
            ) from exc
