"""Data Analysis Agent 本地 smoke test 使用的最小 MCP stdio server。

该 server 只暴露 demo 电商数据源的只读 mock metadata，不执行 SQL，不读取
本地文件、环境变量、密钥或任意系统路径。
"""

from __future__ import annotations

import json
import sys
from typing import Any

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"

DEMO_TABLES: dict[str, dict[str, Any]] = {
    "orders": {
        "description": "Order-level ecommerce facts used by the local demo dataset.",
        "columns": [
            {"name": "order_month", "type": "TEXT", "semantic": "time"},
            {"name": "order_date", "type": "TEXT", "semantic": "time"},
            {"name": "gmv", "type": "REAL", "semantic": "metric"},
            {"name": "quantity", "type": "INTEGER", "semantic": "metric"},
            {"name": "category", "type": "TEXT", "semantic": "dimension"},
            {"name": "region_name", "type": "TEXT", "semantic": "dimension"},
            {"name": "channel_name", "type": "TEXT", "semantic": "dimension"},
        ],
        "row_count_hint": 16,
    },
    "products": {
        "description": "Product dimension table for the ecommerce demo dataset.",
        "columns": [
            {"name": "product_id", "type": "INTEGER", "semantic": "identifier"},
            {"name": "product_name", "type": "TEXT", "semantic": "dimension"},
            {"name": "category", "type": "TEXT", "semantic": "dimension"},
        ],
        "row_count_hint": 8,
    },
    "regions": {
        "description": "Region dimension table for the ecommerce demo dataset.",
        "columns": [
            {"name": "region_id", "type": "INTEGER", "semantic": "identifier"},
            {"name": "region_name", "type": "TEXT", "semantic": "dimension"},
        ],
        "row_count_hint": 4,
    },
}


def main() -> int:
    """运行阻塞式 stdio JSON-RPC 循环。"""

    while True:
        request = _read_message()
        if request is None:
            return 0
        response = _handle_request(request)
        if response is not None:
            _write_message(response)


def _handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """处理一个 MCP JSON-RPC request 或 notification。"""

    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        return _success(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "data-analysis-agent-demo-mcp",
                    "version": "0.2.0-alpha",
                },
            },
        )
    if method == "tools/list":
        return _success(request_id, {"tools": _tool_schemas()})
    if method == "tools/call":
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, -32602, "tools/call params must be an object.")
        return _handle_tool_call(request_id, params)
    return _error(request_id, -32601, f"Unsupported method: {method}")


def _handle_tool_call(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """处理一个只读 demo MCP tool 调用。"""

    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "Tool arguments must be an object.")
    if tool_name == "list_demo_tables":
        payload = list_demo_tables()
        return _success(request_id, _tool_result(payload))
    if tool_name == "describe_demo_table":
        table_name = str(arguments.get("table", "")).strip()
        try:
            payload = describe_demo_table(table_name)
        except KeyError:
            return _error(
                request_id,
                -32602,
                f"Unknown demo table: {table_name}",
                {"allowed_tables": sorted(DEMO_TABLES)},
            )
        return _success(request_id, _tool_result(payload))
    return _error(request_id, -32602, f"Unknown demo MCP tool: {tool_name}")


def _tool_schemas() -> list[dict[str, Any]]:
    """返回 demo tools/list payload。"""

    return [
        {
            "name": "list_demo_tables",
            "description": "List read-only demo ecommerce table metadata.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        },
        {
            "name": "describe_demo_table",
            "description": "Describe one read-only demo ecommerce table.",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["table"],
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": sorted(DEMO_TABLES),
                    }
                },
            },
        },
    ]


def list_demo_tables() -> dict[str, Any]:
    """返回内置 demo 表的紧凑列表。"""

    return {
        "datasource_id": "ecommerce-demo-sqlite",
        "tables": [
            {
                "name": table_name,
                "description": table["description"],
                "row_count_hint": table["row_count_hint"],
            }
            for table_name, table in sorted(DEMO_TABLES.items())
        ],
    }


def describe_demo_table(table: str) -> dict[str, Any]:
    """返回单张内置 demo 表的只读字段 metadata。"""

    normalized = table.strip().lower()
    if normalized not in DEMO_TABLES:
        raise KeyError(normalized)
    table_info = DEMO_TABLES[normalized]
    return {
        "datasource_id": "ecommerce-demo-sqlite",
        "table": normalized,
        "description": table_info["description"],
        "row_count_hint": table_info["row_count_hint"],
        "columns": table_info["columns"],
    }


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    """返回 MCP 兼容的 tool result，并保持文本 payload 有边界。"""

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def _read_message() -> dict[str, Any] | None:
    """从 stdin 读取一个 Content-Length framed JSON-RPC message。"""

    first_line = sys.stdin.buffer.readline()
    if not first_line:
        return None
    headers = _read_headers(first_line)
    content_length = headers.get("content-length")
    if content_length is None:
        raise RuntimeError("Missing Content-Length header.")
    body = sys.stdin.buffer.read(int(content_length))
    return json.loads(body.decode("utf-8"))


def _read_headers(first_line: bytes) -> dict[str, str]:
    """读取 MCP Content-Length headers。"""

    headers: dict[str, str] = {}
    line = first_line
    while line not in (b"\r\n", b"\n", b""):
        decoded = line.decode("ascii").strip()
        if ":" in decoded:
            name, value = decoded.split(":", 1)
            headers[name.lower()] = value.strip()
        line = sys.stdin.buffer.readline()
    return headers


def _write_message(payload: dict[str, Any]) -> None:
    """向 stdout 写入一个 Content-Length framed JSON-RPC message。"""

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def _success(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    """构造一个 JSON-RPC success response。"""

    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _error(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一个 JSON-RPC error response。"""

    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "data": data or {},
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
