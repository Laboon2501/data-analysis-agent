# Local Run Guide

This guide covers local API, LLM smoke, MCP smoke, and Redis/Celery integration
flows. The default test suite does not require Redis, Celery, Postgres, MCP
servers, or real LLM providers.

## Install

Install the project from the repository root before running local API entrypoints.
This installs default runtime dependencies, including `uvicorn[standard]`, plus
development tools when using the `dev` extra.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## One-Command Local Dev

For the fastest local product check, run the API and Web UI together:

```bash
python scripts/run_dev.py
```

Defaults:

- FastAPI backend: `http://127.0.0.1:8000`
- static Web UI: `http://127.0.0.1:5173`
- runner backend: `memory`
- session store: `sqlite`
- session DB: `tmp/dev_sessions.sqlite`
- datasource: `demo/ecommerce_demo.sqlite`, generated automatically if missing

Useful variants:

```bash
python scripts/run_dev.py --no-browser --api-port 8010 --web-port 5174
python scripts/run_dev.py --session-store memory --db-path demo/ecommerce_demo.sqlite
```

If either port is already in use, the script prints which port is blocked and
which flag to change. `Ctrl+C` stops both child processes.

## Memory Backend Local Run

The memory backend is the default and is the recommended first run path.

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
python scripts/run_api.py
```

Defaults:

- runner backend: `memory`
- host: `127.0.0.1`
- port: `8000`
- datasource registry: automatically includes `demo/ecommerce_demo.sqlite` when
  that file exists; `DATA_ANALYSIS_AGENT_DATASOURCE_URL` can add or replace a
  configured datasource
- artifact store: in-memory unless `--use-file-artifact-store` is enabled

Run an API smoke against the local server:

```bash
python scripts/run_integration_smoke.py --api-url http://127.0.0.1:8000
```

Run the same smoke in process, without uvicorn:

```bash
python scripts/run_integration_smoke.py --in-process --runner-backend memory --sse
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/runtime
curl http://127.0.0.1:8000/llm/status
```

Run the minimal API client against the local API:

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --message "Show monthly GMV trend" \
  --stream
```

Run direct analysis plus report/export confirmation:

```bash
python examples/client/demo_flow_client.py \
  --base-url http://127.0.0.1:8000 \
  --confirm-command excel_confirm
```

## Datasource Configuration

The API exposes a small datasource registry for local product validation:

```bash
curl http://127.0.0.1:8000/datasources
curl -X POST http://127.0.0.1:8000/sessions/demo-session/datasource \
  -H "Content-Type: application/json" \
  -d "{\"datasource_id\":\"ecommerce-demo-sqlite\"}"
curl -X POST http://127.0.0.1:8000/datasources/ecommerce-demo-sqlite/profile
```

The API and worker can also create a `SQLAlchemyDataSource` from environment
configuration or CLI flags. The registry returns masked URLs and does not expose
connection-string passwords.

SQLite file path:

```bash
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
DATA_ANALYSIS_AGENT_DATASOURCE_ID=ecommerce-demo-sqlite \
python scripts/run_api.py
```

SQLAlchemy URL:

```bash
DATA_ANALYSIS_AGENT_DATASOURCE_URL=sqlite:///demo/ecommerce_demo.sqlite \
python scripts/run_api.py
```

File datasource upload:

```bash
python scripts/run_api.py --runner-backend memory --upload-dir uploads
curl -X POST http://127.0.0.1:8000/datasources/upload \
  -F "datasource_id=orders-file" \
  -F "table_name=orders" \
  -F "file=@demo/ecommerce_orders_demo.csv"
```

Local file path registration is for trusted local development only and is
disabled by default:

```bash
DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true \
python scripts/run_api.py --runner-backend memory --allow-local-file-paths
curl -X POST http://127.0.0.1:8000/datasources/from-path \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"demo/ecommerce_orders_demo.csv\",\"datasource_id\":\"orders-file\",\"table_name\":\"orders\"}"
```

Supported file datasource formats are CSV, Excel xlsx, and Parquet when the
optional Parquet dependency is available. Uploads are limited by
`DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB` and saved under
`DATA_ANALYSIS_AGENT_UPLOAD_DIR`. Uploaded file bodies are not written to
events, chat history, or session history. Upload and from-path errors are
designed to be human-readable: unsupported extension, empty file, parser
failure, missing `pyarrow` for Parquet, disabled local path mode, file too large,
path traversal, and sensitive path rejection.

If no datasource is configured and `demo/ecommerce_demo.sqlite` exists, the
memory API registers it as `ecommerce-demo-sqlite`. If no datasource exists,
analysis requests return a clarification message instead of executing SQL. If
multiple datasources exist, select one through the session datasource endpoint or
the Web UI before analysis.

## Session History Persistence

The default session history store is memory, which is useful for tests and quick
local runs but disappears when the API process restarts. To persist the
user-visible session list, messages, job summaries, datasource selection, LLM
settings, and artifact refs to SQLite:

```bash
DATA_ANALYSIS_AGENT_SESSION_STORE=sqlite \
DATA_ANALYSIS_AGENT_SESSION_DB_URL=sqlite:///runtime/session_history.sqlite \
DATA_ANALYSIS_AGENT_SESSION_MAX_MESSAGES=200 \
python scripts/run_api.py --runner-backend memory
```

Retention can be triggered manually:

```bash
curl -X POST http://127.0.0.1:8000/sessions/cleanup \
  -H "Content-Type: application/json" \
  -d "{\"ttl_days\":30,\"max_messages\":200}"
```

Session history only stores compact text, job summaries, configuration
summaries, and `artifact:<id>` references. Artifact bodies remain in
`ArtifactStore` and are downloaded through the artifact API.

## Web UI LLM Mode

The Web UI reads `GET /llm/status` and `GET /sessions/{session_id}/llm`. It can
save session-level mode and enabled nodes through
`POST /sessions/{session_id}/llm`.

The Web UI LLM panel is fixed to `real_llm` for product testing and no longer
shows the test LLM mode or LLM `router` toggle. Configure the backend before
starting the API, or save Provider / Model / Base URL / API key in the local Web
UI provider panel:

```bash
DATA_ANALYSIS_AGENT_LLM_PROVIDER=openai_compatible \
DATA_ANALYSIS_AGENT_LLM_MODEL=your-model-name \
DATA_ANALYSIS_AGENT_LLM_BASE_URL=https://your-provider.example.com/v1 \
DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV=YOUR_PROVIDER_API_KEY \
python scripts/run_api.py --runner-backend memory
```

Then open the Web UI, choose one or more of `planner`, `sql_drafter`, and
`insight_writer`, and save the session config. The API reports
`api_key_configured` without returning the key.

## Artifact Directory Strategy

The Celery backend uses `FileArtifactStore` by default so the API process and
worker process can read the same artifacts.

```bash
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
python scripts/run_api.py --runner-backend celery
```

Use the same `DATA_ANALYSIS_AGENT_ARTIFACT_DIR` for both API and worker. Artifact
content remains out of events and chat history; clients fetch it through the
artifact API.

## Redis / Celery Integration Smoke Test

Start Redis and Postgres example services:

```bash
docker compose -f scripts/docker-compose.example.yml up redis postgres
```

Start the API with Celery backend:

```bash
DATA_ANALYSIS_AGENT_RUNNER_BACKEND=celery \
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_UPLOAD_DIR=uploads \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_api.py
```

Start a worker in another terminal:

```bash
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_UPLOAD_DIR=uploads \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_worker.py --execute
```

Run the integration smoke:

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

Without broker/store environment variables, the smoke script prints a clear
message instead of depending on external services during pytest.

## Docker Memory Backend

Build and run a single API container:

```bash
docker compose up --build api
```

The memory compose file uses `.env.example`, maps port `8000`, mounts
`artifact_data` at `/app/artifacts`, and keeps real LLM providers disabled.

Client smoke:

```bash
python examples/client/minimal_client.py --base-url http://127.0.0.1:8000 --stream
```

## Docker Celery Backend

Run API, worker, Redis, and Postgres:

```bash
docker compose -f docker-compose.celery.yml up --build
```

The API and worker share the `artifact_data` and `upload_data` volumes. Redis is
used for broker, result backend, datasource registry cache, and events; Postgres
is provided for checkpoint and session-store configuration examples.

Client smoke:

```bash
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

## DeepSeek / OpenAI-Compatible Smoke Test

Real LLM smoke tests are manual only and never run in pytest.

PowerShell:

```powershell
$env:OPENAI_API_KEY = "YOUR_API_KEY_VALUE"
python scripts/run_llm_smoke.py `
  --provider openai_compatible `
  --model gpt-4.1-mini `
  --base-url https://api.openai.com/v1 `
  --api-key-env OPENAI_API_KEY `
  --llm-node sql_drafter `
  --llm-node insight_writer
```

OpenAI-compatible gateway example:

```bash
python scripts/run_llm_smoke.py \
  --provider openai_compatible \
  --model your-model-name \
  --base-url https://your-provider.example.com/v1 \
  --api-key-env YOUR_PROVIDER_API_KEY \
  --llm-node planner \
  --llm-node sql_drafter \
  --llm-node insight_writer
```

The script prints final response text, SQL, SQL result, insights, errors,
requested/enabled LLM nodes, call count, prompt summaries, and fallback events.

## MCP Smoke Test

Copy the example config:

```bash
cp scripts/mcp.example.json scripts/mcp.local.json
```

List tools:

```bash
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --list-tools
```

List one stdio server:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --list-tools
```

List one SSE server:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_sse_example \
  --list-tools
```

Call one explicitly selected tool:

```bash
python scripts/run_mcp_smoke.py \
  --config scripts/mcp.local.json \
  --server-id local_stdio_example \
  --call-tool mcp__local_stdio_example__tool_name \
  --tool-args '{"name": "orders"}'
```

Safety rules:

- pytest does not start a real MCP server.
- stdio commands are limited to `uvx`, `uv`, `npx`, `node`, `python`,
  `python3`, and `deno`.
- The smoke script uses `shell=False`.
- MCP tools are registered through ToolRegistry and are not freely exposed to
  LLM nodes.

## Common Environment Variables

Runtime:

- `DATA_ANALYSIS_AGENT_RUNNER_BACKEND`: `memory` or `celery`; default `memory`.
- `DATA_ANALYSIS_AGENT_API_HOST`: default `127.0.0.1`.
- `DATA_ANALYSIS_AGENT_API_PORT`: default `8000`.
- `DATA_ANALYSIS_AGENT_API_RELOAD`: enable uvicorn reload when true.
- `DATA_ANALYSIS_AGENT_ARTIFACT_DIR`: local artifact directory.

Datasource and persistence:

- `DATA_ANALYSIS_AGENT_DATASOURCE_URL`: SQLite file path or SQLAlchemy URL.
- `DATA_ANALYSIS_AGENT_DATASOURCE_ID`: datasource identifier stored in state.
- `DATA_ANALYSIS_AGENT_REDIS_URL`: Redis URL for cache/event stores.
- `DATA_ANALYSIS_AGENT_DATABASE_URL`: default database URL used as datasource
  fallback.
- `DATA_ANALYSIS_AGENT_CHECKPOINT_URL`: Postgres checkpoint URL.
- `DATA_ANALYSIS_AGENT_POSTGRES_URL`: Postgres checkpoint URL fallback.

Celery:

- `DATA_ANALYSIS_AGENT_CELERY_BROKER_URL`: Celery broker URL.
- `DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND`: Celery result backend URL.
- `DATA_ANALYSIS_AGENT_CELERY_QUEUE`: Celery queue name.
- `DATA_ANALYSIS_AGENT_CELERY_TASK_NAME`: Celery task name.
- `DATA_ANALYSIS_AGENT_CELERY_APP`: worker app module for the helper script.
- `DATA_ANALYSIS_AGENT_CELERY_LOG_LEVEL`: worker log level.
- `DATA_ANALYSIS_AGENT_CELERY_CONCURRENCY`: worker concurrency.

Optional memory backend stores:

- `DATA_ANALYSIS_AGENT_USE_REDIS_STORES`: use Redis cache/event stores in memory
  runner.
- `DATA_ANALYSIS_AGENT_USE_POSTGRES_CHECKPOINT`: use Postgres checkpoint store
  in memory runner.
- `DATA_ANALYSIS_AGENT_USE_FILE_ARTIFACT_STORE`: use local file artifact store
  in memory runner.

LLM placeholders:

- `DATA_ANALYSIS_AGENT_LLM_PROVIDER`
- `DATA_ANALYSIS_AGENT_LLM_MODEL`
- `DATA_ANALYSIS_AGENT_LLM_BASE_URL`
- `DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV`

Do not put real API keys in source files, docs examples, committed `.env` files,
or test fixtures.

## Product LLM Config And Session Titles

The local Web UI can save a technical-preview LLM provider config through the API:

- `GET /llm/config` returns a sanitized provider config.
- `POST /llm/config` saves provider, model, base URL, enabled node defaults, and a local API key.
- `POST /llm/test` manually tests the saved or submitted provider config.
- `PATCH /sessions/{session_id}` renames a user-visible session.

The raw API key is never returned by status/config endpoints and must not appear in events,
session history, artifacts, or final responses. In this alpha, the key may be stored in the
local file configured by `DATA_ANALYSIS_AGENT_LLM_CONFIG_PATH`; the default `runtime/` directory
is ignored by git. Session-level LLM settings still store only mode and enabled node aliases.
