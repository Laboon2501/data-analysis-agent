"""MCP smoke script 的纯解析与安全辅助测试。"""

import json
from pathlib import Path

import pytest

from mcp.config import MCPServerConfig
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from mcp.manager import MCPManager
from scripts.run_mcp_smoke import (
    DEFAULT_CONFIG_PATH,
    build_manager_for_config,
    load_smoke_config,
    parse_args,
    parse_tool_arguments,
    registry_tool_names,
    run_smoke,
    structured_error,
    tool_configs_from_mcp_tools,
)


def test_mcp_smoke_parse_args_defaults() -> None:
    """默认 CLI 参数不应触发任何连接或外部命令。"""

    args = parse_args([])

    assert args.config.endswith("mcp.example.json")
    assert args.server_id is None
    assert args.list_tools is False
    assert args.call_tool is None
    assert args.arguments == "{}"


def test_mcp_smoke_parse_args_supports_list_tools_and_tool_args() -> None:
    """CLI 应支持显式 list-tools 和新的 --tool-args 参数名。"""

    args = parse_args(["--list-tools", "--tool-args", '{"table":"orders"}'])

    assert args.list_tools is True
    assert args.tool_args == '{"table":"orders"}'
    assert args.arguments == args.tool_args


def test_mcp_smoke_config_supports_stdio_and_sse(tmp_path) -> None:
    """smoke JSON 配置应支持 stdio 和 SSE 两种结构。"""

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "stdio_server",
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "demo"],
                    },
                    {
                        "server_id": "sse_server",
                        "transport": "sse",
                        "url": "http://127.0.0.1:8000/sse",
                        "headers": {"X-Test": "1"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_smoke_config(config_path)

    assert config.servers[0].transport == "stdio"
    assert config.servers[0].command == "python"
    assert config.servers[1].transport == "sse"
    assert config.servers[1].url == "http://127.0.0.1:8000/sse"
    assert config.servers[1].headers == {"X-Test": "1"}


def test_mcp_smoke_config_accepts_utf8_bom(tmp_path) -> None:
    """PowerShell 编辑后的本地 JSON 可能带 BOM，smoke script 应能读取。"""

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "stdio_server",
                        "transport": "stdio",
                        "command": "python",
                    }
                ]
            }
        ),
        encoding="utf-8-sig",
    )

    config = load_smoke_config(config_path)

    assert config.servers[0].server_id == "stdio_server"


def test_mcp_example_config_includes_disabled_demo_server() -> None:
    """示例配置应包含默认关闭的本地 demo MCP server。"""

    config = load_smoke_config(DEFAULT_CONFIG_PATH)
    demo_server = next(server for server in config.servers if server.server_id == "demo_mcp")

    assert demo_server.enabled is False
    assert demo_server.transport == "stdio"
    assert demo_server.command == "python"
    assert [Path(arg) for arg in demo_server.args] == [
        Path("examples") / "mcp" / "demo_mcp_server.py"
    ]


def test_mcp_smoke_config_rejects_disallowed_stdio_command(tmp_path) -> None:
    """配置解析阶段应拦截白名单外 stdio command。"""

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "unsafe",
                        "transport": "stdio",
                        "command": "bash",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MCPAdapterError) as exc_info:
        load_smoke_config(config_path)

    assert exc_info.value.detail.code is MCPErrorCode.COMMAND_NOT_ALLOWED


def test_mcp_smoke_tool_response_converts_to_registry_names() -> None:
    """tools/list 原始结果应转换为 ToolRegistry 的 MCP namespaced 名称。"""

    manager = MCPManager()
    tools = tool_configs_from_mcp_tools(
        "analytics",
        [
            {
                "name": "schema.read",
                "description": "Read schema.",
                "inputSchema": {"type": "object"},
            }
        ],
    )
    manager.register_server(
        MCPServerConfig(server_id="analytics", transport="fake"),
        tools=tools,
    )

    assert tools[0].registry_name == "mcp__analytics__schema.read"
    assert registry_tool_names(manager) == ["mcp__analytics__schema.read"]


def test_mcp_smoke_parse_tool_arguments_requires_object() -> None:
    """--arguments 必须是 JSON object，不能是数组或字符串。"""

    assert parse_tool_arguments('{"table": "orders"}') == {"table": "orders"}

    with pytest.raises(MCPAdapterError) as exc_info:
        parse_tool_arguments('["orders"]')

    assert exc_info.value.detail.code is MCPErrorCode.INVALID_TOOL_NAME


def test_mcp_smoke_parse_tool_arguments_rejects_invalid_json() -> None:
    """非法 JSON 参数应转成结构化 MCPAdapterError。"""

    with pytest.raises(MCPAdapterError) as exc_info:
        parse_tool_arguments("{table:orders}")

    assert exc_info.value.detail.code is MCPErrorCode.INVALID_TOOL_NAME
    assert "error" in exc_info.value.detail.details


def test_mcp_smoke_structured_error_from_mcp_adapter_error() -> None:
    """结构化错误输出应保留 MCP error code 和 details。"""

    exc = MCPAdapterError(
        detail=MCPErrorDetail(
            code=MCPErrorCode.INVALID_TOOL_NAME,
            message="Invalid tool name.",
            details={"tool_name": "bad"},
        ),
    )

    payload = structured_error(exc)

    assert payload["error_type"] == "MCPAdapterError"
    assert payload["code"] == "invalid_tool_name"
    assert payload["details"] == {"tool_name": "bad"}


def test_mcp_smoke_build_manager_skips_disabled_servers(tmp_path) -> None:
    """disabled server 不应构造 transport 或进入 manager。"""

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "disabled_stdio",
                        "transport": "stdio",
                        "command": "python",
                        "enabled": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = build_manager_for_config(load_smoke_config(config_path))

    assert manager.list_servers() == ()


def test_mcp_smoke_run_lists_and_calls_with_fake_transport(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """smoke CLI 层应通过 manager/registry list 和 call，不执行真实外部命令。"""

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "analytics",
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "fake"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fake_tool = tool_configs_from_mcp_tools(
        "analytics",
        [{"name": "schema.read", "description": "Read schema."}],
    )[0]
    fake_transport = FakeSmokeTransport([fake_tool])
    monkeypatch.setattr(
        "scripts.run_mcp_smoke.build_mcp_transport",
        lambda *_args, **_kwargs: fake_transport,
    )

    output = run_smoke(
        parse_args(
            [
                "--config",
                str(config_path),
                "--server-id",
                "analytics",
                "--list-tools",
                "--call-tool",
                "schema.read",
                "--tool-args",
                '{"table":"orders"}',
            ]
        )
    )

    assert output["servers"] == [
        {
            "server_id": "analytics",
            "transport": "stdio",
            "status": "connected",
        }
    ]
    assert output["tools"] == [
        {
            "server_id": "analytics",
            "raw_tool_name": "schema.read",
            "registry_tool_name": "mcp__analytics__schema.read",
            "description": "Read schema.",
        }
    ]
    assert output["call_result"] == {
        "server_id": "analytics",
        "raw_tool_name": "schema.read",
        "arguments": {"table": "orders"},
    }
    assert fake_transport.connected is False


class FakeSmokeTransport:
    """smoke 脚本测试使用的 fake transport。"""

    def __init__(self, tools):
        self.tools = tools
        self.connected = False

    def connect(self, server_config: MCPServerConfig) -> None:
        """记录连接，不启动真实 server。"""

        self.connected = True

    def disconnect(self, server_id: str) -> None:
        """记录断开。"""

        self.connected = False

    def list_tools(self, server_id: str):
        """返回 fake tools。"""

        return self.tools

    def call_tool(self, server_id: str, raw_tool_name: str, arguments=None):
        """返回 fake call payload。"""

        return {
            "server_id": server_id,
            "raw_tool_name": raw_tool_name,
            "arguments": arguments or {},
        }
