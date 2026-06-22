# Web UI Example

This directory contains a static browser UI for the current FastAPI contract. It
is inspired by the original `Zafer-Liu/Data-Analysis-Agent` web layout, but the
implementation is new vanilla HTML/CSS/JS and does not copy the original Flask
templates, backend harness, agent runtime, or tool dispatcher.

## Recommended One-Command Start

From the repository root, the recommended local path is:

```bash
python scripts/run_dev.py
```

It creates or reuses the demo SQLite database, starts FastAPI at
`http://127.0.0.1:8000`, serves this static UI at `http://127.0.0.1:5173`, and
opens the browser. Use custom ports when the defaults are busy:

```bash
python scripts/run_dev.py --no-browser --api-port 8010 --web-port 5174
```

The manual two-terminal flow below is still useful when you want to restart only
the API or only the static page.

## Start The API

From the repository root:

```bash
python -m pip install -e ".[dev]"
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
python scripts/run_api.py --runner-backend memory
```

The memory runner defaults to the demo datasource when no datasource override is
configured.

## Datasource Panel

The UI calls `GET /datasources` on load. Select `ecommerce-demo-sqlite`, click
`Use for session`, and optionally click `Profile datasource` before analysis.
You can register a local SQLite path, SQLAlchemy URL, trusted local file path,
or upload CSV/Excel from the browser. Parquet is optional and requires
`pyarrow`. Local file path registration requires the API to start with
`DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true` or `--allow-local-file-paths`;
upload uses `DATA_ANALYSIS_AGENT_UPLOAD_DIR` and
`DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB`.

After a file upload succeeds, use this order:

1. Select the uploaded datasource.
2. Click `Profile datasource`.
3. Ask a data question or run open exploration.

Upload and path errors are surfaced in the error panel. Common causes are:

- file size exceeds `DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB`
- unsupported extension
- empty file or missing header row
- parse failure in the CSV/Excel parser
- missing optional `pyarrow` dependency for Parquet
- local path mode is disabled
- sensitive path or path traversal was rejected

## Product Workspace Layout

The page is organized as a small product workspace:

- Left: session list and datasource registry/selection.
- Center: chat answers, inline human approval cards, example prompts, and the
  message composer.
- Right: grouped artifacts, dashboard renderer, errors, and collapsed developer
  details.

Developer details are collapsed by default. SQL, SSE timeline, raw artifact
preview, runtime health, and LLM settings stay in that developer section so the
first screen is not dominated by debug output.

The two sidebar buttons in the top bar collapse the session/datasource panel or
the artifact/developer panel. On narrow screens this keeps the chat column usable
without hiding the workflow controls permanently.

Keyboard shortcuts:

- `Enter`: send the current message.
- `Shift+Enter`: insert a newline in the message box.
- `Esc`: close the active chart/dashboard/raw preview; if no preview is open,
  collapse Developer details.
- `Tab`: move through datasource controls, approval buttons, artifact actions,
  and the composer.

## LLM Settings

The top bar shows LLM mode, provider/model, enabled nodes, API key configured
state, and last-job counters. The LLM panel inside Developer details is fixed
to `real_llm` for product testing. The Web UI does not expose the test LLM mode
or the LLM `router` toggle; only `planner`, `sql_drafter`, and
`insight_writer` can be enabled from the browser. The page never displays API
keys; it sends a key only when you explicitly save provider configuration to
the local backend.

## Start The Static Page

In a second terminal:

```bash
cd examples/web
python -m http.server 5173
```

Open:

```text
http://127.0.0.1:5173
```

Set `API Base URL` to `http://127.0.0.1:8000` if it is not already set.

## Direct Analysis

1. Enter `近 12 个月销售趋势怎么样？`.
2. Click `发送`.
3. The final answer appears in the center chat area.
4. Chart artifacts appear in the grouped artifact list.
5. Open Developer details only when you need the SSE timeline or SQL panel.

## Open Exploration

1. Select command `explore`, or send `帮我看看这个数据库有什么可以分析的。`.
2. Watch the topic generation and analysis events.
3. Read the final exploration summary in the chat area.

## Report / Excel / PPT / Dashboard Confirm

1. Run a direct analysis first.
2. Select command `report`.
3. Send `请基于刚才的分析生成报告大纲。`.
4. When `human_request` appears, use the inline confirmation card in the chat
   area or the shortcut buttons near the input box.
5. Click one of:
   - `Yes / Confirm`
   - `No / Cancel`
   - `Report`
   - `Excel`
   - `PPT`
   - `Dashboard`
6. The UI calls `POST /jobs/{job_id}/approve` and continues listening for events.
7. Confirm fast-path reuses the existing `AnalysisPackage` and `ReportOutline`;
   it does not ask the UI to re-run analysis.

## Artifact Download

Artifacts are displayed as normalized `artifact:<id>` references and grouped as
Charts, Reports, Excel, PPT, Dashboards, and Other artifacts.

- Click `metadata` to call `GET /artifacts/{artifact_id}`.
- Click `Preview chart` for chart JSON artifacts.
- Click `Render dashboard` for dashboard JSON artifacts.
- Click `preview JSON` for generic JSON/text artifacts.
- Click `Download JSON` or `Download content` to call
  `GET /artifacts/{artifact_id}/content`. Download failures are shown in the
  error panel with an explicit message.

The event timeline intentionally does not render large artifact bodies.

## Dashboard Renderer

Dashboard artifacts are still stored as JSON specs and fetched through the
artifact API. The page renders a lightweight dashboard from that spec:

- metric widgets become metric cards.
- chart widgets fetch the referenced chart artifact and render a simple line or
  bar SVG preview.
- table widgets show bounded preview rows when present, otherwise row and column
  metadata.
- insight/text widgets show concise summaries.

Unsupported chart types fall back to a bounded JSON preview. No chart JSON,
dashboard JSON, Excel, PPTX, or report body is copied into SSE events or chat
history.

## Current Placeholders

- MCP and Celery controls are read-only status hints. LLM mode is session-level
  only. Provider / Model / Base URL / API key can be saved in the local backend
  config panel; the raw API key is never shown back in the page.
- Dashboard rendering is intentionally lightweight and does not use ECharts,
  Plotly, React, Vue, or a build pipeline.
