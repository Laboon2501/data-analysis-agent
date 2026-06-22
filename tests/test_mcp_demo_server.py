"""本地 demo MCP server 的只读工具测试。"""

from __future__ import annotations

import json

from examples.mcp.demo_mcp_server import (
    _handle_request,
    _tool_schemas,
    describe_demo_table,
    list_demo_tables,
)


def test_demo_mcp_tool_schemas_are_bounded_and_read_only() -> None:
    """demo server 只暴露两个固定只读工具，不包含路径或密钥入口。"""

    schemas = _tool_schemas()
    names = [tool["name"] for tool in schemas]
    schema_text = json.dumps(schemas, sort_keys=True)

    assert names == ["list_demo_tables", "describe_demo_table"]
    assert schemas[0]["inputSchema"]["additionalProperties"] is False
    assert schemas[1]["inputSchema"]["additionalProperties"] is False
    assert schemas[1]["inputSchema"]["properties"]["table"]["enum"] == [
        "orders",
        "products",
        "regions",
    ]
    assert ".env" not in schema_text.lower()
    assert "api_key" not in schema_text.lower()
    assert "path" not in schema_text.lower()


def test_list_demo_tables_returns_fixed_metadata() -> None:
    """list_demo_tables 返回内置 demo metadata，不访问真实文件系统。"""

    payload = list_demo_tables()

    assert payload["datasource_id"] == "ecommerce-demo-sqlite"
    assert [table["name"] for table in payload["tables"]] == [
        "orders",
        "products",
        "regions",
    ]
    assert all("row_count_hint" in table for table in payload["tables"])


def test_describe_demo_table_returns_orders_columns() -> None:
    """describe_demo_table 能返回 orders 的时间、指标和维度字段。"""

    payload = describe_demo_table("orders")
    column_names = [column["name"] for column in payload["columns"]]

    assert payload["table"] == "orders"
    assert "order_month" in column_names
    assert "order_date" in column_names
    assert "gmv" in column_names
    assert "quantity" in column_names
    assert "category" in column_names


def test_demo_mcp_jsonrpc_tools_call_returns_structured_content() -> None:
    """JSON-RPC tools/call 返回 MCP tool result 和 structuredContent。"""

    response = _handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "describe_demo_table",
                "arguments": {"table": "orders"},
            },
        }
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["table"] == "orders"
    assert result["content"][0]["type"] == "text"


def test_demo_mcp_unknown_table_is_structured_error() -> None:
    """未知表名应返回 JSON-RPC structured error，而不是静默成功。"""

    response = _handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "describe_demo_table",
                "arguments": {"table": "missing"},
            },
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert response["error"]["data"]["allowed_tables"] == [
        "orders",
        "products",
        "regions",
    ]
