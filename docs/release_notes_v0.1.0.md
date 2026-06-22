# Release Notes v0.1.0 Technical Preview

`v0.1.0` should be treated as a technical preview / alpha for the LangGraph rewrite of the
Data-Analysis-Agent. It provides a complete, testable engineering skeleton for a
structured data analysis agent while keeping business logic deterministic and
rule-first by default.

## Current Capabilities

- LangGraph workflows for context profiling, direct analysis, open exploration,
  and report/export fast-path.
- Pydantic schemas for shared `AgentState`, database profiles, analysis plans,
  SQL validation, query results, chart specs, insights, report outlines,
  dashboard specs, human requests, events, and structured errors.
- SQLAlchemy datasource layer with SQLite test/demo support.
- `SQLGuard` enforcing read-only SQL safety before query execution.
- ToolRegistry with category-based registration and per-node allowed tools.
- Rule-based direct analysis path covering simple summaries, time trends, TopN,
  guarded SQL execution, result checks, chart spec selection, chart artifacts,
  insights, and analysis package assembly.
- Rule-based open exploration path that generates, ranks, runs, and summarizes
  candidate analyses.
- Report, Excel, PPTX, and dashboard spec artifact exports behind explicit
  confirm commands.
- Artifact API for metadata and content retrieval without embedding artifact
  bodies in events or chat history.
- FastAPI job API, finite event list endpoint, SSE event stream, approve/cancel
  endpoints, and health checks.
- In-memory job runner by default, with optional Celery/Redis/Postgres/File
  persistence skeletons for local integration.
- Optional OpenAI-compatible LLM adapter, prompt loader, FakeLLM tests, and
  per-node LLM strategy rollout with rule fallback.
- Optional MCP adapter and stdio/SSE smoke tooling, with command allowlist and
  ToolRegistry permissions.
- Offline eval suite and demo ecommerce SQLite dataset.
- Minimal API client examples and Docker compose examples for memory and Celery
  backends.
- A static Web UI console for local demo and frontend-contract validation. It is
  not a finished product UI.

## Known Limits

- Default analysis behavior is rule-based and intentionally narrow.
- The Web UI is a minimal console. It prioritizes demo and contract validation
  over production-grade interaction design.
- Real LLM calls are opt-in and are not exercised by default tests or CI.
- Real MCP servers are only validated through manual smoke scripts.
- Celery/Redis/Postgres support is suitable for local integration hardening but
  still needs production observability, deployment-specific security, and worker
  operations before broad use.
- Dashboard export creates a structured JSON spec artifact, not a rendered UI.
- PPTX export uses a simple generated structure, not a branded visual template.
- SQL validation is conservative and focused on read-only analytical queries.

## Safety Boundaries

- SQL execution must pass `SQLGuard`; write statements are blocked.
- Export tools only run after explicit confirm commands such as `ppt_confirm`,
  `report_confirm`, `excel_confirm`, or `dashboard_confirm`.
- Confirm fast-path reuses existing `AnalysisPackage` and `ReportOutline` and
  does not re-analyze data or regenerate outlines.
- Artifact bodies stay in artifact storage. Events, history, and final responses
  carry only references and lightweight metadata.
- LLM nodes do not receive free access to all tools.
- MCP tools are namespaced as `mcp__{server_id}__{raw_tool_name}` and are exposed
  only through ToolRegistry node permissions.
- MCP stdio commands are allowlisted and executed with `shell=False`.
- `.env`, `.idea`, caches, local artifact directories, and local scratch files
  should not be tracked.

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

Run a minimal client:

```bash
python examples/client/minimal_client.py --base-url http://127.0.0.1:8000 --message "Show monthly GMV trend" --stream
```

Optional manual smoke paths:

```bash
python scripts/run_llm_smoke.py --model your-model --base-url https://provider.example/v1 --api-key-env YOUR_API_KEY --llm-node sql_drafter
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id local_stdio_example --list-tools
docker compose up --build api
docker compose -f docker-compose.celery.yml up --build
```

## Roadmap

- Broaden semantic planning and SQL generation coverage.
- Add production-grade auth, tenant isolation, and artifact access control.
- Harden distributed worker observability and operational runbooks.
- Add richer dashboard rendering outside the backend core.
- Expand real-provider LLM evals and MCP compatibility smoke cases.
