"""MCP stdio / SSE transport 的最小真实连接层。"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Thread
from typing import Any, Protocol, runtime_checkable
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from mcp.config import MCPServerConfig, MCPToolConfig, validate_stdio_command
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail

DEFAULT_MCP_TIMEOUT_SECONDS = 30.0
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


@runtime_checkable
class MCPTransport(Protocol):
    """MCP transport 的最小协议，真实 transport 与 fake transport 共用。"""

    def connect(self, server_config: MCPServerConfig) -> None:
        """连接一个 MCP server，并完成初始化。"""

    def disconnect(self, server_id: str) -> None:
        """关闭一个 MCP server 连接。"""

    def list_tools(self, server_id: str) -> list[MCPToolConfig]:
        """读取 server 暴露的 MCP tools。"""

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """调用一个 MCP tool。"""


@dataclass
class JSONRPCRequestCounter:
    """生成递增 JSON-RPC request id。"""

    next_id: int = 1

    def allocate(self) -> int:
        """返回新的 request id。"""

        request_id = self.next_id
        self.next_id += 1
        return request_id


@dataclass
class MCPStdioTransport(MCPTransport):
    """基于 stdio 的 MCP transport。

    该实现使用 MCP 常见的 Content-Length JSON-RPC framing，不使用 shell=True。
    """

    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS
    process: subprocess.Popen[bytes] | None = None
    counter: JSONRPCRequestCounter = field(default_factory=JSONRPCRequestCounter)
    message_queue: Queue[dict[str, Any] | MCPAdapterError] = field(default_factory=Queue)
    reader_thread: Thread | None = None

    def connect(self, server_config: MCPServerConfig) -> None:
        """启动 allowlist 内的 stdio command，并完成 MCP initialize。"""

        if server_config.command is None:
            raise _mcp_error(
                MCPErrorCode.COMMAND_NOT_ALLOWED,
                "stdio MCP server requires command.",
                {"server_id": server_config.server_id},
            )
        command = validate_stdio_command(server_config.command)
        try:
            self.process = subprocess.Popen(
                [command, *server_config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env={**os.environ, **server_config.env},
            )
        except OSError as exc:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_ERROR,
                "Failed to start MCP stdio server.",
                {"server_id": server_config.server_id, "error": str(exc)},
            ) from exc
        self.reader_thread = Thread(target=self._read_stdout_loop, daemon=True)
        self.reader_thread.start()
        self._initialize()

    def disconnect(self, server_id: str) -> None:
        """关闭 stdio MCP 进程。"""

        _ = server_id
        if self.process is None:
            return
        self.process.terminate()
        self.process = None

    def list_tools(self, server_id: str) -> list[MCPToolConfig]:
        """调用 tools/list，并转换为 MCPToolConfig。"""

        response = self._request("tools/list", {})
        return tool_configs_from_mcp_tools(server_id, tools_from_response(response))

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """通过 tools/call 调用指定 MCP tool。"""

        _ = server_id
        response = self._request(
            "tools/call",
            {
                "name": raw_tool_name,
                "arguments": arguments or {},
            },
        )
        return response.get("result")

    def _initialize(self) -> None:
        """发送 MCP initialize，并发送 initialized notification。"""

        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "data-analysis-agent-mcp",
                    "version": "0.2.0-alpha",
                },
            },
        )
        self._notification("notifications/initialized", {})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON-RPC request，并等待相同 id 的响应。"""

        request_id = self.counter.allocate()
        self._write_jsonrpc(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            response = self._next_message(method)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise _mcp_error(
                    MCPErrorCode.JSON_RPC_ERROR,
                    "MCP stdio request failed.",
                    {"method": method, "error": response["error"]},
                )
            return response

    def _notification(self, method: str, params: dict[str, Any]) -> None:
        """发送 JSON-RPC notification。"""

        self._write_jsonrpc(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": method,
                "params": params,
            }
        )

    def _write_jsonrpc(self, payload: dict[str, Any]) -> None:
        """用 Content-Length framing 写入 JSON-RPC 消息。"""

        if self.process is None or self.process.stdin is None:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_UNAVAILABLE,
                "MCP stdio process is not connected.",
            )
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        try:
            self.process.stdin.write(header + body)
            self.process.stdin.flush()
        except OSError as exc:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_ERROR,
                "Failed to write MCP stdio message.",
                {"error": str(exc)},
            ) from exc

    def _read_stdout_loop(self) -> None:
        """持续读取 stdout，并把完整 JSON-RPC 消息放入队列。"""

        while self.process is not None:
            try:
                self.message_queue.put(self._read_framed_jsonrpc())
            except MCPAdapterError as exc:
                self.message_queue.put(exc)
                return

    def _read_framed_jsonrpc(self) -> dict[str, Any]:
        """从 stdout 读取一条 Content-Length JSON-RPC 消息。"""

        if self.process is None or self.process.stdout is None:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_UNAVAILABLE,
                "MCP stdio process is not connected.",
            )
        first_line = self.process.stdout.readline()
        if not first_line:
            stderr = self._read_stderr_tail()
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_ERROR,
                "MCP stdio server closed stdout.",
                {"stderr": stderr},
            )
        if first_line.lstrip().startswith(b"{"):
            return _loads_json(first_line, "stdio line-delimited message")

        headers = _parse_headers(first_line, self.process.stdout)
        content_length = headers.get("content-length")
        if content_length is None:
            raise _mcp_error(
                MCPErrorCode.PROTOCOL_ERROR,
                "MCP stdio message is missing Content-Length header.",
                {"headers": headers},
            )
        try:
            body_length = int(content_length)
        except ValueError as exc:
            raise _mcp_error(
                MCPErrorCode.PROTOCOL_ERROR,
                "MCP stdio Content-Length header is invalid.",
                {"content_length": content_length},
            ) from exc
        body = self.process.stdout.read(body_length)
        if len(body) != body_length:
            raise _mcp_error(
                MCPErrorCode.PROTOCOL_ERROR,
                "MCP stdio message ended before Content-Length bytes were read.",
                {"expected": body_length, "actual": len(body)},
            )
        return _loads_json(body, "stdio framed message")

    def _next_message(self, method: str) -> dict[str, Any]:
        """按 timeout 等待下一条 JSON-RPC 消息。"""

        try:
            item = self.message_queue.get(timeout=self.timeout_seconds)
        except Empty as exc:
            raise _mcp_error(
                MCPErrorCode.REQUEST_TIMEOUT,
                "Timed out waiting for MCP stdio response.",
                {"method": method, "timeout_seconds": self.timeout_seconds},
            ) from exc
        if isinstance(item, MCPAdapterError):
            raise item
        return item

    def _read_stderr_tail(self) -> str:
        """读取 stderr 末尾片段，避免把大量日志塞进错误。"""

        if self.process is None or self.process.stderr is None:
            return ""
        try:
            return self.process.stderr.read().decode("utf-8", errors="replace")[-500:]
        except OSError:
            return ""


@dataclass
class MCPSSETransport(MCPTransport):
    """基于 SSE 的 MCP transport skeleton。"""

    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS
    event_queue: Queue[dict[str, Any] | MCPAdapterError] = field(default_factory=Queue)
    counter: JSONRPCRequestCounter = field(default_factory=JSONRPCRequestCounter)
    server_config: MCPServerConfig | None = None
    message_url: str | None = None
    reader_thread: Thread | None = None

    def connect(self, server_config: MCPServerConfig) -> None:
        """打开 SSE stream，读取 message endpoint，并完成 MCP initialize。"""

        if server_config.url is None:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_UNAVAILABLE,
                "SSE MCP server requires url.",
                {"server_id": server_config.server_id},
            )
        self.server_config = server_config
        try:
            response = urlopen(
                Request(
                    server_config.url,
                    headers={
                        "Accept": "text/event-stream",
                        **server_config.headers,
                    },
                ),
                timeout=self.timeout_seconds,
            )
        except (OSError, URLError) as exc:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_ERROR,
                "Failed to open MCP SSE stream.",
                {"server_id": server_config.server_id, "url": server_config.url},
            ) from exc
        self.reader_thread = Thread(
            target=self._read_sse_stream,
            args=(response,),
            daemon=True,
        )
        self.reader_thread.start()
        endpoint_event = self._next_event("endpoint")
        self.message_url = urljoin(server_config.url, endpoint_event["data"])
        self._initialize()

    def disconnect(self, server_id: str) -> None:
        """SSE reader 使用 daemon thread，手动 smoke 场景下无需额外关闭。"""

        _ = server_id

    def list_tools(self, server_id: str) -> list[MCPToolConfig]:
        """调用 tools/list，并转换为 MCPToolConfig。"""

        response = self._request("tools/list", {})
        return tool_configs_from_mcp_tools(server_id, tools_from_response(response))

    def call_tool(
        self,
        server_id: str,
        raw_tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """通过 SSE tools/call 调用指定 MCP tool。"""

        _ = server_id
        response = self._request(
            "tools/call",
            {
                "name": raw_tool_name,
                "arguments": arguments or {},
            },
        )
        return response.get("result")

    def _initialize(self) -> None:
        """发送 MCP initialize，并发送 initialized notification。"""

        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "data-analysis-agent-mcp",
                    "version": "0.2.0-alpha",
                },
            },
        )
        self._notification("notifications/initialized", {})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """向 SSE message endpoint POST request，并等待 message event。"""

        request_id = self.counter.allocate()
        self._post_jsonrpc(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            event = self._next_event("message")
            payload = _loads_json(event["data"].encode("utf-8"), "SSE message event")
            if payload.get("id") != request_id:
                continue
            if "error" in payload:
                raise _mcp_error(
                    MCPErrorCode.JSON_RPC_ERROR,
                    "MCP SSE request failed.",
                    {"method": method, "error": payload["error"]},
                )
            return payload

    def _notification(self, method: str, params: dict[str, Any]) -> None:
        """向 SSE message endpoint POST notification。"""

        self._post_jsonrpc(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": method,
                "params": params,
            }
        )

    def _post_jsonrpc(self, payload: dict[str, Any]) -> None:
        """向 MCP SSE message endpoint POST JSON-RPC 消息。"""

        if self.message_url is None or self.server_config is None:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_UNAVAILABLE,
                "MCP SSE message endpoint is unavailable.",
            )
        try:
            with urlopen(
                Request(
                    self.message_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        **self.server_config.headers,
                    },
                    method="POST",
                ),
                timeout=self.timeout_seconds,
            ):
                return
        except (OSError, URLError) as exc:
            raise _mcp_error(
                MCPErrorCode.TRANSPORT_ERROR,
                "Failed to post MCP SSE message.",
                {"url": self.message_url},
            ) from exc

    def _read_sse_stream(self, response: Any) -> None:
        """读取 SSE stream，并把完整 event 放入队列。"""

        event_name = "message"
        data_lines: list[str] = []
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data_lines:
                        self.event_queue.put(
                            {
                                "event": event_name,
                                "data": "\n".join(data_lines),
                            }
                        )
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
        except OSError as exc:
            self.event_queue.put(
                _mcp_error(
                    MCPErrorCode.TRANSPORT_ERROR,
                    "Failed to read MCP SSE stream.",
                    {"error": str(exc)},
                )
            )

    def _next_event(self, event_name: str) -> dict[str, Any]:
        """按 timeout 等待指定类型的 SSE event。"""

        while True:
            try:
                item = self.event_queue.get(timeout=self.timeout_seconds)
            except Empty as exc:
                raise _mcp_error(
                    MCPErrorCode.REQUEST_TIMEOUT,
                    "Timed out waiting for MCP SSE event.",
                    {"event": event_name, "timeout_seconds": self.timeout_seconds},
                ) from exc
            if isinstance(item, MCPAdapterError):
                raise item
            if item.get("event") == event_name:
                return item


def build_mcp_transport(
    server_config: MCPServerConfig,
    *,
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
) -> MCPTransport:
    """根据 server transport 类型构造 MCP transport。"""

    if server_config.transport == "stdio":
        return MCPStdioTransport(timeout_seconds=timeout_seconds)
    if server_config.transport == "sse":
        return MCPSSETransport(timeout_seconds=timeout_seconds)
    raise _mcp_error(
        MCPErrorCode.TRANSPORT_UNAVAILABLE,
        "Only stdio and sse transports can be built automatically.",
        {
            "server_id": server_config.server_id,
            "transport": server_config.transport,
        },
    )


def tool_configs_from_mcp_tools(
    server_id: str,
    tool_items: list[dict[str, Any]],
) -> list[MCPToolConfig]:
    """把 MCP tools/list 原始结果转换为 MCPToolConfig。"""

    return [
        MCPToolConfig(
            server_id=server_id,
            raw_tool_name=str(item["name"]),
            description=item.get("description"),
            input_schema=item.get("inputSchema") or item.get("input_schema") or {},
        )
        for item in tool_items
    ]


def tools_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """从 MCP JSON-RPC response 中读取 tools/list 结果。"""

    result = response.get("result") or {}
    tools = result.get("tools") or []
    if not isinstance(tools, list):
        raise _mcp_error(
            MCPErrorCode.PROTOCOL_ERROR,
            "MCP tools/list result must contain a tools list.",
            {"result": result},
        )
    return tools


def _parse_headers(first_line: bytes, stdout: Any) -> dict[str, str]:
    """解析 Content-Length framing headers。"""

    headers: dict[str, str] = {}
    line = first_line
    while line not in (b"\r\n", b"\n", b""):
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            name, value = decoded.split(":", 1)
            headers[name.lower()] = value.strip()
        line = stdout.readline()
    return headers


def _loads_json(raw_payload: bytes, context: str) -> dict[str, Any]:
    """读取 JSON object；非法 JSON 统一转换为 MCPAdapterError。"""

    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _mcp_error(
            MCPErrorCode.PROTOCOL_ERROR,
            f"Invalid JSON in MCP {context}.",
            {"error": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise _mcp_error(
            MCPErrorCode.PROTOCOL_ERROR,
            f"MCP {context} must be a JSON object.",
            {"payload_type": type(payload).__name__},
        )
    return payload


def _mcp_error(
    code: MCPErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> MCPAdapterError:
    """构造 MCP transport 使用的结构化错误。"""

    return MCPAdapterError(
        MCPErrorDetail(
            code=code,
            message=message,
            details=details or {},
        )
    )
