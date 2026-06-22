# MCP Demo Server

This directory contains a tiny local MCP stdio server used to validate the
project MCP adapter and `scripts/run_mcp_smoke.py`.

It is a local demo server only:

- It is not enabled by default.
- It does not run in pytest or CI.
- It does not execute arbitrary commands.
- It does not read `.env`, credentials, or arbitrary system paths.
- It exposes read-only mock metadata for the ecommerce demo datasource.
- It does not give any LLM free access to MCP tools.

## Tools

The server exposes two tools:

- `list_demo_tables`: returns compact metadata for built-in demo tables.
- `describe_demo_table`: returns bounded column metadata for one table.

Both tools use fixed in-process metadata. They do not execute SQL.

## Manual Smoke

From the repository root:

```bash
cp scripts/mcp.example.json scripts/mcp.local.json
```

Edit `scripts/mcp.local.json` and set the `demo_mcp` server to
`"enabled": true`.

List tools:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --list-tools
```

Call `list_demo_tables`:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --call-tool mcp__demo_mcp__list_demo_tables
```

Call `describe_demo_table`:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --call-tool mcp__demo_mcp__describe_demo_table \
  --tool-args "{\"table\":\"orders\"}"
```

`scripts/run_mcp_smoke.py` converts raw MCP tool names to ToolRegistry names such
as `mcp__demo_mcp__list_demo_tables`. MCP tools still enter only the `mcp`
category and are visible to graph nodes only when explicitly allowed by
ToolRegistry node permissions.
