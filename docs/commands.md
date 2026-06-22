# Commands

Run commands from the repository root unless noted otherwise.

## Install

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Test, Lint, Format, Eval

```bash
python -m pytest
python -m evals.runner
python -m ruff check .
python -m ruff format --check .
```

## One-Command Local Dev

Start FastAPI, the static Web UI, and the demo datasource together:

```bash
python scripts/run_dev.py
```

By default this uses the memory runner and a local SQLite session history store
at `tmp/dev_sessions.sqlite`, so Web UI sessions survive local restarts.

Common options:

```bash
python scripts/run_dev.py --no-browser --api-port 8010 --web-port 5174
python scripts/run_dev.py --runner-backend memory --session-store memory
python scripts/run_dev.py --db-path demo/ecommerce_demo.sqlite --no-create-demo-db
```

Supported flags include `--api-host`, `--api-port`, `--web-host`, `--web-port`,
`--runner-backend memory|celery`, `--db-path`, `--no-browser`,
`--no-create-demo-db`, `--session-store memory|sqlite|sqlalchemy`,
`--session-db-url`, and `--reload`.

## Demo Dataset

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
```

Default arguments:

```bash
python scripts/create_demo_db.py
```

## Demo Flow

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
```

Useful variants:

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite --skip-sse
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite --llm-node sql_drafter
```

LLM nodes are optional and default off. The Web UI exposes only `planner`,
`sql_drafter`, and `insight_writer`; lower-level test scripts may still enable
the router explicitly for routing regression checks.

## FastAPI App

Memory backend:

```bash
python scripts/run_api.py
```

Memory backend with an explicit datasource and file artifacts:

```bash
python scripts/run_api.py \
  --runner-backend memory \
  --datasource-url demo/ecommerce_demo.sqlite \
  --artifact-dir artifacts \
  --use-file-artifact-store
```

Explicit memory backend:

```bash
python scripts/run_api.py --runner-backend memory --host 127.0.0.1 --port 8000
```

Celery backend:

```bash
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_api.py --runner-backend celery
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/runtime
curl http://127.0.0.1:8000/llm/status
curl http://127.0.0.1:8000/sessions/demo-session/llm
curl -X POST http://127.0.0.1:8000/sessions/demo-session/llm \
  -H "Content-Type: application/json" \
  -d "{\"mode\":\"real_llm\",\"enabled_nodes\":[\"planner\",\"sql_drafter\",\"insight_writer\"]}"
```

## Integration Smoke

In-process memory check:

```bash
python scripts/run_integration_smoke.py --in-process --runner-backend memory --sse
```

Against a running API:

```bash
python scripts/run_integration_smoke.py --api-url http://127.0.0.1:8000
```

File datasource smoke in-process:

```bash
python scripts/run_integration_smoke.py \
  --in-process \
  --datasource-kind file \
  --file-registration-mode upload \
  --file-path demo/ecommerce_orders_demo.csv \
  --file-table-name orders \
  --profile-datasource \
  --include-exploration \
  --include-exports \
  --message "Show monthly GMV trend"
```

Export fast-path smoke:

```bash
python scripts/run_integration_smoke.py --in-process --include-exports --sse
```

Celery backend check:

```bash
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

## Minimal API Clients

Run after starting `python scripts/run_api.py` or a Docker API service.

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --message "Show monthly GMV trend" \
  --stream
```

Run a direct analysis plus report/export confirm flow:

```bash
python examples/client/demo_flow_client.py \
  --base-url http://127.0.0.1:8000 \
  --confirm-command excel_confirm
```

Cancel example:

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --message "Prepare a report" \
  --command report \
  --cancel
```

## LLM Smoke

Manual only. Set your API key in the environment before running.

```bash
python scripts/run_llm_smoke.py \
  --provider openai_compatible \
  --model gpt-4.1-mini \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY \
  --llm-node sql_drafter \
  --llm-node insight_writer
```

This script does not run in pytest or CI.

## Real LLM Eval

Manual only. It requires explicit LLM node selection and provider config.

```bash
python scripts/run_llm_eval.py \
  --tag sql \
  --llm-node sql_drafter \
  --llm-node insight_writer \
  --model your-model-name \
  --base-url https://your-provider.example.com/v1 \
  --api-key-env YOUR_PROVIDER_API_KEY
```

Equivalent module command:

```bash
python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --strategy real-llm \
  --tag router \
  --tag sql \
  --llm-nodes sql_drafter insight_writer \
  --llm-model your-model-name \
  --llm-base-url https://your-provider.example.com/v1 \
  --llm-api-key-env YOUR_PROVIDER_API_KEY
```

Default `python -m evals.runner` remains rule-based and does not call real LLMs.
Useful optional LLM eval tags include `router`, `sql`, `file-datasource`, and
`export`.

## MCP Smoke

List configured MCP tools:

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.example.json --list-tools
```

Run one local stdio MCP server from a copied config:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --list-tools
```

Run the bundled read-only demo MCP server. Copy `scripts/mcp.example.json` to
`scripts/mcp.local.json`, set `demo_mcp` to `enabled=true`, then run:

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
  --tool-args "{\"table\":\"orders\"}"
```

Run one local SSE MCP server from a copied config:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_sse_example \
  --list-tools
```

Call one explicitly selected MCP tool:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --call-tool mcp__local_stdio_example__tool_name \
  --tool-args "{\"name\":\"orders\"}"
```

This script does not run in pytest or CI. stdio commands are allowlisted and are
not executed through a shell. MCP tools enter ToolRegistry permissions only and
are not automatically exposed to LLM nodes.

## Worker Command Helper

Print the Celery worker command:

```bash
python scripts/run_worker.py
```

Execute the printed command only after configuring a real Celery app module:

```bash
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_worker.py --execute
```

## Redis, Postgres, Celery Local Services

Start example support services:

```bash
docker compose -f scripts/docker-compose.example.yml up redis postgres
```

The default project path does not require these services. They are only for
manual local integration checks.

## Docker Compose

Memory backend API:

```bash
docker compose up --build api
```

Celery backend with API, worker, Redis, and Postgres:

```bash
docker compose -f docker-compose.celery.yml up --build
```

Smoke against the Docker API:

```bash
python examples/client/minimal_client.py --base-url http://127.0.0.1:8000 --stream
python scripts/run_integration_smoke.py \
  --api-url http://127.0.0.1:8000 \
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
