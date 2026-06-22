# v0.2.0-alpha Release Checklist

Use this checklist before tagging `v0.2.0-alpha`. The release remains a
technical preview: rule-first by default, no real provider calls in CI, and no
external Redis/Celery/Postgres/MCP dependency for the default test path.

## Architecture

- [ ] No hidden ReAct loop is present.
- [ ] No `BusinessAgent.run()` style giant agent class is present.
- [ ] No giant tool dispatcher is present.
- [ ] LangGraph workflows remain explicit graph flows.
- [ ] Core workflow state is carried through Pydantic schemas, especially
  `AgentState`.
- [ ] LLM strategy is opt-in for the supported node aliases only: `router`,
  `planner`, `sql_drafter`, and `insight_writer`.
- [ ] MCP tools enter `ToolRegistry` only and remain restricted by per-node
  allowed tools.
- [ ] Report/Excel/PPT/dashboard confirm fast-path reuses existing
  `AnalysisPackage` and `ReportOutline`.

## Datasources

- [ ] SQLite and SQLAlchemy datasources can be registered and profiled.
- [ ] File datasources support CSV and Excel, with Parquet optional when the
  dependency is installed.
- [ ] `from-path` registration is disabled by default and requires an explicit
  local-development setting.
- [ ] Uploads enforce extension, size, empty-file, parser, path traversal, and
  sensitive-path checks.
- [ ] Datasource metadata returns safe names, table metadata, row counts, and
  columns without leaking passwords or full sensitive local paths.
- [ ] File bodies are not written to events, chat history, session history, or
  final responses.

## Web UI

- [ ] The Web UI is vanilla HTML/CSS/JS with no React, Vue, or build chain.
- [ ] Session, datasource, LLM settings, artifacts, dashboard renderer, and
  Developer details are visible and separated.
- [ ] `hi`, `hello`, `你好`, and help messages return guidance instead of SQL.
- [ ] Inline human approval supports report, Excel, PPT, and dashboard confirms.
- [ ] Artifact groups show charts, reports, Excel, PPT, and dashboards without
  embedding artifact bodies in history.
- [ ] Dashboard artifacts render from the artifact API; chart previews use
  bounded JSON/SVG previews.
- [ ] Keyboard and narrow-screen checks still pass: Enter sends, Shift+Enter
  inserts a newline, Esc closes previews or collapses Developer details.

## Runtime Checks

Run from the repository root:

```bash
python scripts/run_demo_flow.py --db-path demo/ecommerce_demo.sqlite
python -m evals.runner
python -m pytest
python -m ruff check .
python -m ruff format --check .
git diff --check
git status --short --ignored
```

Expected result:

- Demo flow completes context profile, direct analysis, open exploration, report
  outline, Excel export, PPT export, and dashboard export.
- Offline evals pass with default rule strategy and no real LLM calls.
- Pytest, Ruff, format check, and diff whitespace check pass.
- `git status --short --ignored` does not show tracked local secrets, IDE files,
  caches, local SQLite demo DBs, upload files, or artifacts.

## Optional Manual Smoke Checks

These checks are not part of CI and should only run when local providers or
services are configured:

```bash
python scripts/run_llm_smoke.py --model your-model --base-url https://provider.example/v1 --api-key-env YOUR_API_KEY --llm-node sql_drafter
python scripts/run_llm_eval.py --llm-node sql_drafter --model your-model --base-url https://provider.example/v1 --api-key-env YOUR_API_KEY
python scripts/run_mcp_smoke.py --config scripts/mcp.local.json --server-id demo_mcp --list-tools
python scripts/run_integration_smoke.py --runner-backend celery --sse --include-exports
```

## Documentation

- [ ] `README.md` identifies the release as `v0.2.0-alpha` technical preview.
- [ ] `docs/release_notes_v0.2.0-alpha.md` covers capabilities, limits, safety,
  local run, Web UI, file datasource, optional LLM/MCP/Celery, and roadmap.
- [ ] `docs/commands.md` matches script entry points.
- [ ] `docs/api.md` matches FastAPI routes.
- [ ] `docs/events.md` covers every `EventType`.
- [ ] `docs/frontend_flow.md` covers session, datasource, LLM, inline approval,
  artifact, dashboard, and file datasource flows.
- [ ] `docs/local_run.md` covers memory backend, SQLite session store, file
  datasource registration, and optional distributed smoke paths.
- [ ] `docs/deployment.md` matches Docker and compose files.
- [ ] `.env.example` includes key runtime, datasource, upload, artifact,
  session, Celery, Redis, checkpoint, and optional LLM variables without real
  secrets.
