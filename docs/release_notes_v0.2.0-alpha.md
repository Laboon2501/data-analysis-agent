# Release Notes v0.2.0-alpha Technical Preview

`v0.2.0-alpha` is a technical-preview release of the LangGraph rewrite of
Data-Analysis-Agent. It keeps the default runtime deterministic and rule-first,
while adding the product-facing surfaces needed for local validation: a Web UI,
datasource registry, file datasource support, session history, dashboard
rendering, stronger evals, and optional integration smoke paths.

The Python package version is `0.2.0a0`, the PEP 440 equivalent of the
`v0.2.0-alpha` tag.

## New Capabilities Since v0.1.0

- Static Web UI workspace in `examples/web` with sessions, datasource controls,
  LLM status/settings, inline human approval, grouped artifacts, chart preview,
  dashboard rendering, and collapsed Developer details.
- Session APIs and pluggable Session Store with memory default and optional
  SQLite/SQLAlchemy persistence for user-visible chat history.
- Datasource registry APIs for SQLite, SQLAlchemy URLs, safe local file path
  registration, and browser uploads.
- File datasource support for CSV and Excel, with Parquet available when the
  optional backend dependency is installed.
- Upload safety checks for extension, size, empty files, parser failures, path
  traversal, sensitive paths, and disabled local path mode.
- Dashboard JSON artifact renderer in the Web UI, using artifact metadata/content
  APIs instead of a separate dashboard backend.
- LLM runtime status APIs and session-level node toggles for `router`,
  `planner`, `sql_drafter`, and `insight_writer`, with no API key exposure.
- Stronger fake/real LLM eval cases covering chat/help routing, SQLGuard
  blocking, fallback, invalid JSON, file datasources, and export cases.
- MCP stdio/SSE transport smoke path plus a local read-only demo MCP server.
- Docker/Celery integration profile with shared artifact/upload volumes and
  manual smoke scripts.

## Current Capabilities

- LangGraph workflows for context profiling, direct analysis, open exploration,
  and report/export fast-path.
- Pydantic schemas for shared `AgentState`, database profiles, analysis plans,
  SQL validation, query results, chart specs, insights, report outlines,
  dashboard specs, human requests, events, and structured errors.
- SQLAlchemy datasource layer with SQLite demo/test support.
- File datasource layer that converts supported local/uploaded files into a
  read-only queryable table for existing graph flows.
- `SQLGuard` enforcing read-only SQL safety before query execution.
- ToolRegistry with category-based registration and per-node allowed tools,
  including MCP tools under the `mcp` category.
- Rule-based direct analysis path for simple summaries, time trends, TopN,
  guarded SQL execution, result checks, chart artifacts, insights, and analysis
  package assembly.
- Rule-based open exploration path that generates, ranks, runs, and summarizes
  candidate analyses.
- Report, Excel, PPTX, and dashboard spec artifact exports behind explicit
  confirm commands.
- Artifact API for metadata and content retrieval without embedding artifact
  bodies in events, final responses, or session history.
- FastAPI job API, finite event list endpoint, SSE event stream, approve/cancel
  endpoints, datasource APIs, LLM status APIs, session APIs, and health checks.
- In-memory job runner by default, with optional Celery/Redis/Postgres/File
  persistence paths for local integration.
- Optional OpenAI-compatible LLM adapter, prompt loader, FakeLLM tests, and
  per-node LLM strategy rollout with rule fallback.
- Optional MCP adapter and stdio/SSE smoke tooling, with command allowlist and
  ToolRegistry permissions.
- Offline eval suite and ecommerce demo fixtures for SQLite and CSV.

## Known Limits

- This is not a production product release. It is an alpha / technical preview.
- Default analysis behavior is rule-based and intentionally narrow.
- Web UI is a local integration workspace, not a polished multi-user SaaS UI.
- Real LLM calls are opt-in and are not exercised by default tests or CI.
- Real MCP servers and Celery/Redis/Postgres services are validated only through
  manual smoke paths.
- File uploads are local-development oriented and do not include authentication,
  multi-tenant isolation, malware scanning, or data retention controls.
- Parquet requires an optional dependency such as `pyarrow`; without it the API
  returns a structured dependency error.
- Dashboard rendering is lightweight HTML/SVG/JSON preview, not a full BI
  frontend.
- PPTX export uses a simple generated structure, not a branded visual template.
- SQL validation is conservative and focused on read-only analytical queries.

## Safety Boundaries

- SQL execution must pass `SQLGuard`; write statements are blocked.
- Export tools only run after explicit confirm commands such as `ppt_confirm`,
  `report_confirm`, `excel_confirm`, or `dashboard_confirm`.
- Confirm fast-path reuses existing `AnalysisPackage` and `ReportOutline` and
  does not re-analyze data or regenerate outlines.
- Artifact bodies stay in artifact storage. Events, chat history, session
  history, and final responses carry only references and lightweight metadata.
- Uploaded file bodies are converted into datasource tables and are not written
  into events, history, or final responses.
- Datasource responses mask connection strings and avoid exposing sensitive
  local paths.
- Real LLM mode is disabled unless local backend provider config or equivalent
  environment variables are configured; API keys are never returned to the frontend.
- LLM nodes do not receive free access to all tools.
- MCP tools are namespaced as `mcp__{server_id}__{raw_tool_name}` and are exposed
  only through ToolRegistry node permissions.
- MCP stdio commands are allowlisted and executed with `shell=False`.
- `.env`, `.idea`, caches, local artifact/upload directories, local SQLite demo
  DBs, and scratch files should not be tracked.

## Local Run

Install and run the default checks:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
python -m evals.runner
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Start the memory backend API:

```bash
python scripts/run_api.py --runner-backend memory --datasource-url demo/ecommerce_demo.sqlite
```

Start the Web UI:

```bash
cd examples/web
python -m http.server 5173
```

Open `http://127.0.0.1:5173`, select the demo datasource, profile it if needed,
and ask a direct analysis question such as:

```text
近 12 个月销售趋势怎么样？
```

## File Datasource Usage

Upload a CSV through the API:

```bash
curl -X POST http://127.0.0.1:8000/datasources/upload \
  -F "datasource_id=orders-file" \
  -F "table_name=orders" \
  -F "file=@demo/ecommerce_orders_demo.csv"
```

Trusted local file-path registration is disabled by default. Enable it only for
local development:

```bash
DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true \
python scripts/run_api.py --runner-backend memory --allow-local-file-paths
```

Then register a file path:

```bash
curl -X POST http://127.0.0.1:8000/datasources/from-path \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"demo/ecommerce_orders_demo.csv\",\"datasource_id\":\"orders-file\",\"table_name\":\"orders\"}"
```

## Optional Paths

Real LLM smoke and eval are manual:

```bash
python scripts/run_llm_smoke.py --model your-model --base-url https://provider.example/v1 --api-key-env YOUR_API_KEY --llm-node sql_drafter
python scripts/run_llm_eval.py --tag sql --llm-node sql_drafter --model your-model --base-url https://provider.example/v1 --api-key-env YOUR_API_KEY
```

MCP demo smoke is manual:

```bash
cp scripts/mcp.example.json scripts/mcp.local.json
# set demo_mcp enabled=true in scripts/mcp.local.json
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --list-tools
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --call-tool mcp__demo_mcp__list_demo_tables
```

Docker/Celery integration is manual:

```bash
docker compose -f docker-compose.celery.yml up --build
python scripts/run_integration_smoke.py --api-url http://127.0.0.1:8000 --runner-backend celery --sse --include-exports
```

## Roadmap

- Broaden semantic planning and SQL generation coverage without weakening
  SQLGuard.
- Add authentication, tenant isolation, artifact access control, and upload
  governance before production use.
- Harden distributed worker observability, retry behavior, and operations.
- Expand real-provider LLM eval coverage and MCP compatibility smoke cases.
- Add richer dashboard rendering in the frontend without moving large payloads
  into events or history.
