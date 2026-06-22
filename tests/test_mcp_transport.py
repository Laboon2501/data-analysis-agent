"""MCP transport 的 stdio / SSE 单元测试。"""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.request import Request

import pytest

from mcp.config import MCPServerConfig
from mcp.errors import MCPAdapterError, MCPErrorCode
from mcp.transport import MCPSSETransport, MCPStdioTransport, build_mcp_transport


class FakeProcess:
    """模拟 subprocess.Popen 返回值，不启动真实外部进程。"""

    def __init__(self, stdout_payload: bytes) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout_payload)
        self.stderr = io.BytesIO()
        self.terminated = False

    def terminate(self) -> None:
        """记录关闭，不触碰真实进程。"""

        self.terminated = True


def test_stdio_transport_uses_allowlisted_command_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdio transport 应使用 allowlist command，并且 shell=False。"""

    responses = b"".join(
        [
            _framed({"jsonrpc": "2.0", "id": 1, "result": {}}),
            _framed(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "tools": [
                            {
                                "name": "schema.read",
                                "description": "Read schema.",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    },
                }
            ),
            _framed(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {"content": [{"type": "text", "text": "ok"}]},
                }
            ),
        ]
    )
    fake_process = FakeProcess(responses)
    captured: dict[str, Any] = {}

    def fake_popen(args: list[str], **kwargs: Any) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr("mcp.transport.subprocess.Popen", fake_popen)
    transport = MCPStdioTransport(timeout_seconds=0.5)

    transport.connect(
        MCPServerConfig(
            server_id="analytics",
            transport="stdio",
            command="python",
            args=["-m", "fake_mcp_server"],
        )
    )
    tools = transport.list_tools("analytics")
    result = transport.call_tool("analytics", "schema.read", {"table": "orders"})

    assert captured["args"] == ["python", "-m", "fake_mcp_server"]
    assert captured["kwargs"]["shell"] is False
    assert tools[0].raw_tool_name == "schema.read"
    assert tools[0].registry_name == "mcp__analytics__schema.read"
    assert result == {"content": [{"type": "text", "text": "ok"}]}
    assert b"Content-Length:" in fake_process.stdin.getvalue()
    assert b"tools/call" in fake_process.stdin.getvalue()


def test_stdio_transport_converts_jsonrpc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdio JSON-RPC error 应转换为结构化 MCPAdapterError。"""

    fake_process = FakeProcess(
        _framed(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "method not found"},
            }
        )
    )
    monkeypatch.setattr("mcp.transport.subprocess.Popen", lambda *_, **__: fake_process)

    with pytest.raises(MCPAdapterError) as exc_info:
        MCPStdioTransport(timeout_seconds=0.5).connect(
            MCPServerConfig(server_id="analytics", transport="stdio", command="python")
        )

    assert exc_info.value.detail.code is MCPErrorCode.JSON_RPC_ERROR
    assert exc_info.value.detail.details["method"] == "initialize"


def test_sse_transport_lists_and_calls_tools_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE transport 测试使用 fake urlopen，不进行真实联网。"""

    sse_lines = [
        b"event: endpoint\n",
        b"data: /messages\n",
        b"\n",
        b"event: message\n",
        b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n',
        b"\n",
        b"event: message\n",
        b'data: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"profile.read"}]}}\n',
        b"\n",
        b"event: message\n",
        b'data: {"jsonrpc":"2.0","id":3,"result":{"ok":true}}\n',
        b"\n",
    ]
    requests: list[Request] = []

    def fake_urlopen(request: Request, timeout: float) -> Any:
        requests.append(request)
        if request.data is None:
            return iter(sse_lines)
        return FakeHTTPResponse()

    monkeypatch.setattr("mcp.transport.urlopen", fake_urlopen)
    transport = MCPSSETransport(timeout_seconds=0.5)

    transport.connect(
        MCPServerConfig(
            server_id="analytics",
            transport="sse",
            url="http://127.0.0.1:8000/sse",
            headers={"X-Test": "1"},
        )
    )
    tools = transport.list_tools("analytics")
    result = transport.call_tool("analytics", "profile.read", {"table": "orders"})

    assert tools[0].registry_name == "mcp__analytics__profile.read"
    assert result == {"ok": True}
    assert requests[0].full_url == "http://127.0.0.1:8000/sse"
    assert any(request.full_url == "http://127.0.0.1:8000/messages" for request in requests)


def test_build_mcp_transport_rejects_fake_transport() -> None:
    """自动 transport factory 只负责 stdio / SSE，fake transport 由测试显式注入。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        build_mcp_transport(MCPServerConfig(server_id="analytics", transport="fake"))

    assert exc_info.value.detail.code is MCPErrorCode.TRANSPORT_UNAVAILABLE


class FakeHTTPResponse:
    """模拟 urllib response context manager。"""

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def _framed(payload: dict[str, Any]) -> bytes:
    """构造 Content-Length framed JSON-RPC 消息。"""

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
