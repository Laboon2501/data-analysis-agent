# Data Analysis Agent LangGraph

This repository is a LangGraph rewrite skeleton for a structured data-analysis
agent inspired by `Zafer-Liu/Data-Analysis-Agent`. It is not a general chat bot:
the system is organized around explicit workflows for database profiling,
direct analysis, open exploration, chart artifacts, report/export confirmation,
job execution, SSE events, and offline regression evals.

The current implementation is a v0.2.0-alpha technical preview and is
intentionally rule-first. LLM, MCP, Redis,
Postgres, Celery, and external provider integrations are available as adapters
or manual smoke-test paths, but default tests and demo commands do not require
real external services or network calls.

Runtime configuration is centralized in `app/config.py`. Defaults keep the
system on the in-memory backend; Redis, Celery, Postgres checkpoints, file
artifacts, datasource URLs, and LLM provider placeholders are opt-in through
environment variables or script flags. Start from `.env.example` for local
integration work, but do not commit real secrets.

## Architecture Overview

The project uses LangGraph workflows with a shared Pydantic `AgentState`.
Core graph families:

- Context Manager: builds and caches `DatabaseProfile` from datasource schema.
- Direct Analysis: interprets a clear question, drafts guarded SQL, executes it,
  creates chart artifacts, writes insights, and builds an `AnalysisPackage`.
- Schema QA / Data Inspection: answers field, column, metric, dimension, and
  "what can this file analyze" questions from `DatabaseProfile` without running
  aggregate SQL.
- Open Exploration: creates candidate topics from `DatabaseProfile`, ranks them,
  runs a small set of simple analyses, and summarizes findings.
- Report Export: generates an outline first, waits for explicit confirmation,
  then uses a fast-path for report, PPT, Excel, or dashboard artifacts.

More detail is in [docs/architecture.md](docs/architecture.md). API details are
in [docs/api.md](docs/api.md), event contracts are in [docs/events.md](docs/events.md),
frontend flow notes are in [docs/frontend_flow.md](docs/frontend_flow.md), and
deployment notes are in [docs/deployment.md](docs/deployment.md). Release
readiness notes for this alpha are in
[docs/release_notes_v0.2.0-alpha.md](docs/release_notes_v0.2.0-alpha.md).

## Directory Structure

```text
app/                 FastAPI app, harness, worker backends
datasource/          Datasource protocol and SQLAlchemy datasource
demo/                Ecommerce demo SQL fixture and demo notes
docs/                API, events, architecture, commands, local run docs
evals/               Offline eval cases, runner, and metrics
examples/client/     Minimal stdlib API client examples
examples/web/        Static browser UI for local FastAPI integration
graphs/              LangGraph workflow builders
guards/              SQL, output, retry, timeout, cancel policies
llm/                 LLM protocol, fake client, OpenAI-compatible adapter
mcp/                 MCP config, transport, manager, adapter, and errors
nodes/               Small workflow nodes used by graphs
persistence/         In-memory and optional external store interfaces
prompts/             Narrow prompt files for optional LLM strategies
schemas/             Pydantic state and domain schemas
scripts/             Local smoke, demo, API, and integration scripts
tests/               Unit, graph, API, eval, and script tests
tools/               Registry, schema, SQL, chart, and export tools
```

## Quick Start

Use Python 3.11.x for local development.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Start the full local development workspace with one command:

```bash
python scripts/run_dev.py
```

This creates or reuses `demo/ecommerce_demo.sqlite`, starts the FastAPI memory
backend at `http://127.0.0.1:8000`, serves the static Web UI at
`http://127.0.0.1:5173`, uses a local SQLite session history store at
`tmp/dev_sessions.sqlite`, opens the browser, and shuts both subprocesses down
on `Ctrl+C`. Use alternate ports when needed:

```bash
python scripts/run_dev.py --no-browser --api-port 8010 --web-port 5174
```

Run the default verification suite:

```bash
python -m pytest
python -m evals.runner
python -m ruff check .
python -m ruff format --check .
```

## Demo Database

Generate or refresh the local SQLite ecommerce demo database:

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
```

Run the end-to-end local demo flow with the in-memory backend:

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
```

The demo runs context profiling, direct analysis, open exploration, report
outline generation, and confirmed Excel/PPT/dashboard exports. It prints job IDs,
events, final responses, and artifact refs. It does not call a real LLM by
default.

## FastAPI Memory Backend

Start the local FastAPI app with the default in-memory runner:

```bash
python scripts/run_api.py
```

Submit a chat job:

```bash
curl -X POST http://127.0.0.1:8000/sessions/demo-session/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"Show monthly GMV trend\",\"command\":\"none\"}"
```

Inspect job status, events, SSE, and artifacts:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/runtime
curl http://127.0.0.1:8000/datasources
curl -X POST http://127.0.0.1:8000/sessions/demo-session/datasource \
  -H "Content-Type: application/json" \
  -d "{\"datasource_id\":\"ecommerce-demo-sqlite\"}"
curl -X POST http://127.0.0.1:8000/datasources/ecommerce-demo-sqlite/profile
curl http://127.0.0.1:8000/jobs/{job_id}
curl http://127.0.0.1:8000/jobs/{job_id}/events
curl http://127.0.0.1:8000/jobs/{job_id}/events/stream
curl http://127.0.0.1:8000/artifacts/{artifact_id}
curl http://127.0.0.1:8000/artifacts/{artifact_id}/content
```

For an in-process API smoke check without starting uvicorn:

```bash
python scripts/run_integration_smoke.py --in-process --runner-backend memory --sse
```

File datasource smoke:

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

## Minimal API Client Examples

After starting the local API, run the smallest stdlib client:

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

The examples print job IDs, event types, final responses, artifact refs, and
artifact download byte sizes. They do not implement a UI and do not require real
LLM, Redis, Celery, or Postgres services.

## Static Web UI Example

The Web UI is a lightweight technical-preview workspace, not a finished
multi-user product UI. It defaults to rule mode unless the backend is started
with explicit LLM configuration.

After starting the local API, serve the static browser UI from a second terminal:

```bash
cd examples/web
python -m http.server 5173
```

Open `http://127.0.0.1:5173`, keep `API Base URL` set to
`http://127.0.0.1:8000`, refresh the datasource panel, select
`ecommerce-demo-sqlite`, optionally click `Profile datasource`, and ask:

```text
杩?12 涓湀閿€鍞秼鍔挎€庝箞鏍凤紵
```

The page uses a product-oriented layout: session and datasource controls on the
left, chat/answer/inline approval in the center, and grouped artifacts plus a
dashboard renderer on the right. Developer details stay collapsed by default and
contain SSE events, SQL, raw artifact preview, runtime health, and LLM settings.
Top-bar sidebar controls keep the chat column usable on narrow screens.
Keyboard shortcuts are intentionally simple: `Enter` sends, `Shift+Enter` adds a
line break, and `Esc` closes previews or collapses Developer details.
Human approval appears as an assistant card in the chat stream and as shortcut
buttons near the input box; export confirms still call the existing fast-path
commands.
Dashboard artifacts can be rendered in the browser as lightweight metric, chart,
table, and insight cards. Chart artifacts are previewed as simple line or bar
SVG charts when possible, with a bounded JSON fallback for unsupported chart
types.
Datasource registration supports SQLite paths, SQLAlchemy URLs, local file path
registration in trusted local mode, and browser CSV/Excel upload. Parquet can be
registered when the optional Parquet dependency is available. The upload panel
shows supported formats, upload size limits, and the next step
`select datasource -> Profile datasource -> ask a question`. Error messages call
out unsupported extensions, empty files, parser failures, missing Parquet
dependencies, disabled local path mode, and rejected sensitive paths. MCP/Celery
configuration remains intentionally read-only in the Web UI. The top status strip
shows runner backend, datasource status, current datasource, session id, LLM
mode, provider/model, enabled LLM nodes, and whether a local backend API key is
configured. `LLM: rule` means no real provider call is being made.

The Web UI LLM settings panel is session scoped and fixed to `real_llm` for
product testing. The browser no longer exposes the test LLM mode or the LLM
`router` toggle; it can enable only `planner`, `sql_drafter`, and
`insight_writer`.
Real LLM mode requires a saved local Provider / Model / Base URL / API key
config, or equivalent backend environment configuration. The API key is stored
only in local backend configuration and is never returned to the browser.

`scripts/run_dev.py` uses a local SQLite Session Store by default so visible
chat history survives local restarts. A standalone `scripts/run_api.py` launch
still defaults to the in-memory Session Store unless configured otherwise. The
Session Store keeps visible chat messages, job summaries, datasource/LLM
selections, and artifact refs for Web UI switching. It does not store artifact file contents, graph
checkpoints, or raw event streams. For local persistence, start the API with a
SQLite-backed store:

```bash
DATA_ANALYSIS_AGENT_SESSION_STORE=sqlite \
DATA_ANALYSIS_AGENT_SESSION_DB_URL=sqlite:///runtime/session_history.sqlite \
python scripts/run_api.py --runner-backend memory
```

Optional retention settings are `DATA_ANALYSIS_AGENT_SESSION_TTL_DAYS` and
`DATA_ANALYSIS_AGENT_SESSION_MAX_MESSAGES`. The cleanup API trims history only;
artifact files remain in `ArtifactStore`.

The UI structure was informed by the Apache-2.0 upstream project, with details
recorded in [docs/third_party_notices.md](docs/third_party_notices.md).

## Docker Quick Start

Memory backend:

```bash
docker compose up --build api
```

Celery backend with API, worker, Redis, and Postgres:

```bash
docker compose -f docker-compose.celery.yml up --build
```

Both compose files use `.env.example` values. The Celery profile shares
`artifact_data` and `upload_data` volumes between API and worker, and configures
shared Redis/Postgres-backed event, checkpoint, and session stores. Do not commit
a real `.env`. See [docs/deployment.md](docs/deployment.md) for production notes.

## Eval And Tests

Run offline regression evals:

```bash
python -m evals.runner
```

Run optional real LLM evals manually:

```bash
python scripts/run_llm_eval.py \
  --tag sql \
  --llm-node sql_drafter \
  --llm-node insight_writer \
  --model your-model-name \
  --base-url https://your-provider.example.com/v1 \
  --api-key-env YOUR_PROVIDER_API_KEY
```

Run tests:

```bash
python -m pytest
```

The eval suite uses SQLite fixtures and rule strategy by default. It checks
intent, SQL safety, table/field match, result non-empty rate, chart type,
artifact generation, ReAct/tool-free-call violations, and large-payload leaks.
Real LLM eval is opt-in and is not part of default CI. Optional LLM cases can be
filtered with tags such as `router`, `sql`, `file-datasource`, and `export`;
their summaries include fallback, invalid JSON, SQLGuard block, and no-SQL
chat/help rates.

## Optional Smoke Tests

LLM smoke tests are manual and require a local API key environment variable:

```bash
python scripts/run_llm_smoke.py \
  --provider openai_compatible \
  --model gpt-4.1-mini \
  --base-url https://api.openai.com/v1 \
  --api-key-env OPENAI_API_KEY \
  --llm-node sql_drafter \
  --llm-node insight_writer
```

MCP smoke tests are manual and use a local JSON config:

```bash
cp scripts/mcp.example.json scripts/mcp.local.json
# edit scripts/mcp.local.json and set demo_mcp enabled=true
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
  --tool-args '{"table":"orders"}'
```

Redis/Celery/Postgres integration scripts are also manual:

```bash
docker compose -f scripts/docker-compose.example.yml up redis postgres
DATA_ANALYSIS_AGENT_CELERY_BROKER_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_REDIS_URL=redis://127.0.0.1:6379/0 \
DATA_ANALYSIS_AGENT_ARTIFACT_DIR=artifacts \
DATA_ANALYSIS_AGENT_DATASOURCE_URL=demo/ecommerce_demo.sqlite \
python scripts/run_worker.py --execute
python scripts/run_api.py --runner-backend celery
python scripts/run_integration_smoke.py --runner-backend celery --sse
```

See [docs/commands.md](docs/commands.md) and [scripts/README.md](scripts/README.md)
for all local commands and environment variables.

## Safety Boundaries

- SQL execution must go through `SQLGuard`; write statements are blocked.
- Export tools require explicit confirm commands such as `ppt_confirm`,
  `report_confirm`, `excel_confirm`, or `dashboard_confirm`.
- Confirmed export jobs use the report fast-path and do not re-analyze data or
  regenerate outlines.
- Chart HTML, dashboard specs, PPTX, Excel, and report bodies stay in artifact
  storage. Events, chat history, and final responses only carry artifact refs.
- LLM strategy is opt-in per node and falls back to rule strategy on structured
  errors or invalid JSON.
- MCP stdio commands are allowlisted and executed with `shell=False`; MCP tools
  are registered through the adapter and remain restricted by ToolRegistry node
  permissions, never automatically exposed to LLM nodes.

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
