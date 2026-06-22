# Local LLM Smoke Test

This directory contains manual scripts for local provider checks. They are not part of
`pytest` or CI, and they should only be run by a developer who has configured a real
provider key locally.

## Environment

Set the API key in an environment variable. Do not write the key into source files.

PowerShell:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

Bash:

```bash
export OPENAI_API_KEY="sk-..."
```

You can use another variable name with `--api-key-env`.

## Run

Example with an OpenAI-compatible endpoint:

```bash
python scripts/run_llm_smoke.py \
  --provider openai_compatible \
  --model gpt-4.1-mini \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY \
  --llm-node sql_drafter \
  --llm-node insight_writer
```

Example with a custom OpenAI-compatible gateway:

```bash
python scripts/run_llm_smoke.py \
  --model your-model-name \
  --base-url https://your-gateway.example.com/v1 \
  --api-key-env YOUR_GATEWAY_API_KEY
```

The script creates an in-memory SQLite demo database, runs the direct analysis graph once,
and prints:

- `final_response_text`
- SQL draft
- SQL result
- insight
- structured errors
- requested LLM node names
- enabled graph node strategy map
- LLM call count
- system prompt first lines used by each LLM call
- fallback events when an LLM node falls back to rule strategy

## Notes

- The script does not implement streaming.
- It does not give the LLM free access to tools.
- The LLM output still goes through JSON parsing and existing SQL validation.
- The default test suite does not run this script and does not make network requests.
- If an LLM node falls back to rule output, inspect `fallback_events` to see the node,
  error type, and structured error code such as `json_invalid`.

# Local MCP Smoke Test

`run_mcp_smoke.py` is a manual script for checking MCP stdio or SSE servers locally.
It is not imported by the default graph path, and pytest only tests its parsing and
safety helpers. The default test suite does not start MCP servers, open SSE streams,
or execute external commands.

## MCP Config

Start from the example file:

```bash
cp scripts/mcp.example.json scripts/mcp.local.json
```

Edit `scripts/mcp.local.json` and enable only the server you want to test. Do not
put real secrets in this file. If a server needs credentials, read them from your
local environment in the MCP server process itself.

Supported structures:

```json
{
  "servers": [
    {
      "server_id": "local_stdio_example",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "your_mcp_server_module"],
      "env": {},
      "enabled": true
    },
    {
      "server_id": "local_sse_example",
      "transport": "sse",
      "url": "http://127.0.0.1:8000/sse",
      "headers": {},
      "enabled": true
    }
  ]
}
```

## MCP Run

List tools and print their ToolRegistry names:

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --list-tools
```

Run one enabled stdio server:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --list-tools
```

Run the bundled read-only demo server. First copy the example config and set
`demo_mcp` to `enabled=true` in your local copy:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --list-tools

python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --call-tool mcp__demo_mcp__list_demo_tables

python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id demo_mcp \
  --call-tool mcp__demo_mcp__describe_demo_table \
  --tool-args '{"table": "orders"}'
```

Run one enabled SSE server:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_sse_example \
  --list-tools
```

Optionally call one tool:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --call-tool mcp__local_stdio_example__tool_name \
  --tool-args '{"name": "orders"}'
```

You can pass a raw tool name only when `--server-id` is also provided.

## MCP Safety Notes

- stdio commands are restricted to the allowlist in `mcp/config.py`: `uvx`, `uv`,
  `npx`, `node`, `python`, `python3`, and `deno`.
- The script uses `shell=False`; it does not execute arbitrary shell strings.
- The script lists MCP tools and can call one explicitly requested tool. It does
  not give any LLM free access to MCP tools.
- Tool names are still converted to `mcp__{server_id}__{raw_tool_name}` before
  registry use.

# Local API / Worker Integration Smoke

These scripts are for local manual integration checks. They are not part of
pytest or CI, and the default test suite does not require Redis, Celery, or
Postgres.

## Start Support Services

The example compose file provides Redis and Postgres, plus optional API/worker
service examples:

```bash
docker compose -f scripts/docker-compose.example.yml up redis postgres
```

To include the example API/worker services:

```bash
docker compose -f scripts/docker-compose.example.yml --profile app up
```

The compose file uses local-only placeholder credentials. Replace them for any
non-local environment.

## Run API

Memory runner is the default:

```bash
python scripts/run_api.py
```

Choose backend through CLI or environment:

```bash
DATA_ANALYSIS_AGENT_RUNNER_BACKEND=memory python scripts/run_api.py
DATA_ANALYSIS_AGENT_RUNNER_BACKEND=celery python scripts/run_api.py
```

Useful environment variables:

- `DATA_ANALYSIS_AGENT_RUNNER_BACKEND`: `memory` or `celery`; default `memory`.
- `DATA_ANALYSIS_AGENT_API_HOST`: default `127.0.0.1`.
- `DATA_ANALYSIS_AGENT_API_PORT`: default `8000`.
- `DATA_ANALYSIS_AGENT_API_RELOAD`: enable uvicorn reload when true.
- `DATA_ANALYSIS_AGENT_USE_REDIS_STORES`: use Redis cache/event stores in memory runner.
- `DATA_ANALYSIS_AGENT_USE_POSTGRES_CHECKPOINT`: use Postgres checkpoint store in memory runner.
- `DATA_ANALYSIS_AGENT_USE_FILE_ARTIFACT_STORE`: persist artifacts to local filesystem.
- `DATA_ANALYSIS_AGENT_REDIS_URL`: Redis URL for cache/event stores. If omitted, a Redis Celery broker URL can be reused for Celery job/event stores.
- `DATA_ANALYSIS_AGENT_DATABASE_URL`: shared database URL fallback.
- `DATA_ANALYSIS_AGENT_CHECKPOINT_URL`: Postgres checkpoint URL for job state.
- `DATA_ANALYSIS_AGENT_POSTGRES_URL`: SQLAlchemy Postgres URL for checkpoints.
- `DATA_ANALYSIS_AGENT_ARTIFACT_DIR`: local artifact directory.
- `DATA_ANALYSIS_AGENT_DATASOURCE_URL`: SQLite file path or SQLAlchemy datasource URL.
- `DATA_ANALYSIS_AGENT_DATASOURCE_ID`: datasource identifier stored in state.
- `DATA_ANALYSIS_AGENT_CELERY_BROKER_URL`: Celery broker URL.
- `DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND`: optional Celery result backend URL.
- `DATA_ANALYSIS_AGENT_CELERY_QUEUE`: Celery queue name.
- `DATA_ANALYSIS_AGENT_CELERY_TASK_NAME`: Celery task name; defaults to `app.workers.celery_tasks.run_agent_job`.

## Run Worker

`run_worker.py` prints a concrete Celery worker command by default:

```bash
python scripts/run_worker.py
```

To execute the printed command locally, pass `--execute` after configuring a
broker and shared Redis stores:

```bash
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_worker.py --execute
```

The default Celery app path is `app.workers.celery_app:celery_app`, which loads
`app.workers.celery_tasks.run_agent_job`.

## Integration Smoke

Against a running local API:

```bash
python scripts/run_integration_smoke.py --api-url http://127.0.0.1:8000
```

In-process memory mode, without uvicorn:

```bash
python scripts/run_integration_smoke.py --in-process --runner-backend memory
```

Include SSE fetch:

```bash
python scripts/run_integration_smoke.py --in-process --runner-backend memory --sse
```

For Celery backend mode:

```bash
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_UPLOAD_DIR=uploads \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_api.py --runner-backend celery
python scripts/run_integration_smoke.py \
  --runner-backend celery \
  --sse \
  --datasource-kind file \
  --file-registration-mode upload \
  --file-path demo/ecommerce_orders_demo.csv \
  --file-table-name orders \
  --profile-datasource \
  --include-exploration \
  --include-exports
```

Without the broker/store environment variables, the smoke script prints a clear
skip message instead of relying on Redis, Celery, or Postgres during pytest. With
the variables configured and a worker running, it submits a real Celery task and
polls job status/events.
For file datasource smoke, API and worker must share the same
`DATA_ANALYSIS_AGENT_UPLOAD_DIR` and `DATA_ANALYSIS_AGENT_ARTIFACT_DIR`.
