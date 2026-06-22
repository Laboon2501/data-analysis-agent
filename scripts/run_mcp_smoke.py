"""本地 MCP stdio/SSE smoke test 脚本。

该脚本只在开发者手动执行时连接 MCP server；pytest 不会启动外部进程或网络服务。
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp.adapter import mcp_tool_name, parse_mcp_tool_name, register_mcp_tools
from mcp.config import MCPServerConfig
from mcp.errors import MCPAdapterError, MCPErrorCode, MCPErrorDetail
from mcp.manager import MCPManager
from mcp.transport import (
    DEFAULT_MCP_TIMEOUT_SECONDS,
    build_mcp_transport,
)
from mcp.transport import (
    tool_configs_from_mcp_tools as tool_configs_from_mcp_tools,
)
from schemas._base import StrictBaseModel
from tools.registry import ToolRegistry

DEFAULT_CONFIG_PATH = Path(__file__).with_name("mcp.example.json")


class MCPSmokeConfig(StrictBaseModel):
    """MCP smoke test 的 JSON 配置结构。"""

    servers: list[MCPServerConfig]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 smoke test CLI 参数。"""

    parser = argparse.ArgumentParser(description="Run a local MCP stdio/SSE smoke test.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to MCP smoke JSON config.",
    )
    parser.add_argument(
        "--server-id",
        help="Optional server id to run. Defaults to every enabled server.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List MCP tools after connecting. This is implicit when --call-tool is omitted.",
    )
    parser.add_argument(
        "--call-tool",
        help="Optional tool to call. Use mcp__server__tool or raw tool name with --server-id.",
    )
    parser.add_argument(
        "--tool-args",
        "--arguments",
        dest="tool_args",
        default="{}",
        help="JSON object arguments for --call-tool.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_MCP_TIMEOUT_SECONDS,
        help="Transport timeout for manual smoke calls.",
    )
    args = parser.parse_args(argv)
    args.arguments = args.tool_args
    return args


def load_smoke_config(path: str | Path) -> MCPSmokeConfig:
    """读取并校验 MCP smoke JSON 配置。"""

    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return MCPSmokeConfig.model_validate(payload)


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    """解析 --tool-args JSON object。"""

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise _smoke_error(
            MCPErrorCode.INVALID_TOOL_NAME,
            "--tool-args must be valid JSON.",
            {"error": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise _smoke_error(
            MCPErrorCode.INVALID_TOOL_NAME,
            "--tool-args must be a JSON object.",
            {"arguments_type": type(parsed).__name__},
        )
    return parsed


def build_manager_for_config(
    config: MCPSmokeConfig,
    *,
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
    server_id: str | None = None,
) -> MCPManager:
    """从 smoke 配置构造 MCPManager；不会连接 disabled server。"""

    manager = MCPManager()
    for server_config in config.servers:
        if not server_config.enabled:
            continue
        if server_id is not None and server_config.server_id != server_id:
            continue
        manager.register_server(
            server_config,
            transport=build_mcp_transport(
                server_config,
                timeout_seconds=timeout_seconds,
            ),
        )
    return manager


def registry_tool_names(manager: MCPManager) -> list[str]:
    """返回 manager 中所有 MCP tools 转换后的 ToolRegistry 名称。"""

    registry = register_mcp_tools(ToolRegistry(), manager)
    return [tool.name for tool in registry.get_tools_by_category("mcp")]


def tools_payload(manager: MCPManager) -> list[dict[str, Any]]:
    """输出 raw tool name 与 ToolRegistry namespaced name 的对应关系。"""

    return [
        {
            "server_id": tool.server_id,
            "raw_tool_name": tool.raw_tool_name,
            "registry_tool_name": mcp_tool_name(tool.server_id, tool.raw_tool_name),
            "description": tool.description,
        }
        for tool in manager.list_tools()
    ]


def structured_error(exc: Exception) -> dict[str, Any]:
    """把异常转换为可打印的结构化错误。"""

    if isinstance(exc, MCPAdapterError):
        return {
            "error_type": type(exc).__name__,
            "code": exc.detail.code.value,
            "message": exc.detail.message,
            "details": exc.detail.details,
        }
    return {
        "error_type": type(exc).__name__,
        "code": "unexpected_error",
        "message": str(exc),
        "details": {},
    }


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    """执行一次手动 MCP smoke test。"""

    config = load_smoke_config(args.config)
    manager = build_manager_for_config(
        config,
        timeout_seconds=args.timeout_seconds,
        server_id=args.server_id,
    )
    connected_server_ids: list[str] = []
    try:
        for server in manager.list_servers():
            manager.connect(server.server_id)
            connected_server_ids.append(server.server_id)

        output: dict[str, Any] = {
            "servers": [
                {
                    "server_id": server.server_id,
                    "transport": server.transport,
                    "status": manager.connection_status(server.server_id).value,
                }
                for server in manager.list_servers()
            ],
            "tools": tools_payload(manager),
            "tool_registry_names": registry_tool_names(manager),
        }
        if args.list_tools or not args.call_tool:
            output["listed_tool_count"] = len(output["tools"])
        if args.call_tool:
            output["call_result"] = call_registry_tool(
                manager,
                args.call_tool,
                server_id=args.server_id,
                arguments=parse_tool_arguments(args.tool_args),
            )
        return output
    finally:
        for active_server_id in connected_server_ids:
            manager.disconnect(active_server_id)


def call_registry_tool(
    manager: MCPManager,
    tool_name: str,
    *,
    server_id: str | None,
    arguments: dict[str, Any],
) -> Any:
    """通过 ToolRegistry 适配后的 handler 调用一个 MCP tool。"""

    if tool_name.startswith("mcp__"):
        registry_name = tool_name
    else:
        if server_id is None:
            raise _smoke_error(
                MCPErrorCode.INVALID_TOOL_NAME,
                "Raw tool name requires --server-id.",
                {"tool_name": tool_name},
            )
        registry_name = mcp_tool_name(server_id, tool_name)
    parse_mcp_tool_name(registry_name)
    registry = register_mcp_tools(ToolRegistry(), manager)
    tool = registry.get_tool(registry_name)
    return tool.handler(**arguments)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。"""

    args = parse_args(argv)
    try:
        print(json.dumps(run_smoke(args), indent=2, sort_keys=True, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"error": structured_error(exc)}, indent=2, sort_keys=True))
        return 1


def _smoke_error(
    code: MCPErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> MCPAdapterError:
    """构造 smoke test 使用的 MCPAdapterError。"""

    return MCPAdapterError(
        MCPErrorDetail(
            code=code,
            message=message,
            details=details or {},
        )
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
