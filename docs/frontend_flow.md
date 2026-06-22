# Frontend Integration Flow

## Static Web UI Example

`examples/web` provides a static browser UI for manual frontend integration.
It uses the current FastAPI contract directly and does not copy the original
Flask backend harness or tool dispatcher.
It is a lightweight technical-preview workspace, not a finished multi-user
product UI. The layout keeps sessions and datasources on the left, chat and
inline human approval in the center, and grouped artifacts plus dashboard
rendering on the right. Developer details are collapsed by default.

Start the API:

```bash
python scripts/run_api.py --runner-backend memory
```

Start the static page:

```bash
cd examples/web
python -m http.server 5173
```

Open:

```text
http://127.0.0.1:5173
```

The page calls:

- `GET /sessions`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `GET /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/messages`
- `GET /sessions/{session_id}/jobs`
- `GET /datasources`
- `POST /datasources`
- `POST /datasources/from-path`
- `POST /datasources/upload`
- `GET /datasources/{datasource_id}`
- `POST /datasources/{datasource_id}/profile`
- `POST /sessions/{session_id}/datasource`
- `GET /sessions/{session_id}/datasource`
- `GET /llm/status`
- `GET /sessions/{session_id}/llm`
- `POST /sessions/{session_id}/llm`
- `POST /sessions/{session_id}/chat`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/events`
- `GET /jobs/{job_id}/events/stream`
- `POST /jobs/{job_id}/approve`
- `POST /jobs/{job_id}/cancel`
- `GET /artifacts/{artifact_id}`
- `GET /artifacts/{artifact_id}/content`
- `GET /health`
- `GET /health/runtime`

The top status strip displays API base URL, runner backend, datasource status,
current datasource, session id, LLM mode, provider/model, enabled LLM nodes, and
whether an API key env var is configured. The default is `LLM: rule`, which means
the backend is not calling a real provider.

Field and datasource-inspection questions such as `把字段告诉我`,
`这个文件有哪些字段？`, and `哪些字段可以作为指标？` are routed to the
controlled Schema QA graph. The answer appears in the chat stream as a field
summary card with table names, field types, sample-value summaries, candidate
metrics, candidate dimensions, and suggested analysis directions. This path does
not run aggregate SQL and does not expose uploaded file bodies.

Recommended manual checks:

1. Refresh datasources and select `ecommerce-demo-sqlite` when it is available.
2. Click `Profile datasource` and confirm the profile job reaches a terminal state.
3. Send `hi` and confirm it returns help without SQL.
4. Click the example prompt `近 12 个月销售趋势怎么样？`.
5. Confirm final response and chart artifact appear in the main panels.
6. Request a report outline after a completed analysis.
7. Use the inline approval card or composer shortcuts for `Excel`, `PPT`,
   `Dashboard`, or `Report`.
8. Click artifact metadata, preview, render, and download links.
9. Expand Developer details only when you need SSE, SQL, raw events, runtime
   health, or LLM settings.
10. Use the top bar sidebar buttons on narrow screens to keep the chat column
    readable while still preserving session/datasource and artifact controls.

Keyboard behavior:

- `Enter` sends the message.
- `Shift+Enter` inserts a newline.
- `Esc` closes chart/dashboard/raw artifact preview; if no preview is active, it
  collapses Developer details.
- Human approval buttons, artifact actions, send, cancel, and datasource controls
  are normal focusable controls and should be reachable with `Tab`.

Datasource registration supports SQLite paths, SQLAlchemy URLs, local file path
registration in explicitly enabled local mode, and browser upload for CSV/Excel
files. Parquet is optional and only works when the backend has `pyarrow`.
Uploaded files are converted server-side to a queryable internal SQLite table;
only basename-style metadata and `artifact:<id>` refs are displayed in the
browser. The LLM settings panel lives in Developer details and is fixed to
`real_llm` for product testing. It hides the test LLM mode and the LLM `router`
toggle, and can enable only `planner`, `sql_drafter`, and `insight_writer` from
the browser. `real_llm` is allowed when Provider / Model / Base URL / API key
have been saved in local backend configuration or supplied by environment
variables. The page never displays the raw API key. MCP settings and Celery control
remain read-only placeholders.

## Session History Flow

1. On load, the frontend calls `POST /sessions` for the current session id and
   then `GET /sessions` to render the session list.
2. Clicking a session calls `GET /sessions/{session_id}`,
   `GET /sessions/{session_id}/messages`, and
   `GET /sessions/{session_id}/jobs`.
3. The chat area is rebuilt from persisted `ChatMessage` records.
4. Artifact refs are restored from session/message/job summaries and are fetched
   through the artifact API only when the user asks for metadata or content.
5. `POST /sessions/{session_id}/chat` automatically writes the user message,
   assistant summary, job summary, datasource id, LLM mode, and artifact refs.
6. Deleting a session calls `DELETE /sessions/{session_id}`. This removes the
   visible history only; it does not remove artifact files or checkpoint/event
   records.
7. The Web UI reads `GET /health/runtime` to show the active session store type.
   `memory` is marked temporary; `sqlite` / `sqlalchemy` indicate persistent
   user-visible history. Manual cleanup is available through
   `POST /sessions/cleanup`.

## LLM Settings Flow

1. Frontend calls `GET /llm/status` and `GET /sessions/{session_id}/llm`.
2. The status strip shows `mode`, `provider/model`, enabled nodes,
   `api_key_configured`, and last-job LLM event counters.
3. User changes mode or node checkboxes and clicks save.
4. Frontend calls `POST /sessions/{session_id}/llm` with only mode and node
   aliases.
5. If `real_llm` is requested without backend API key configuration, the API
   returns `400` with a clear message.
6. Later analysis jobs use LLM strategy only for the enabled nodes; fallback
   events remain visible in SSE. Greeting/help messages still short-circuit
   before SQL or analysis LLM nodes.

## Datasource Selection Flow

1. Frontend calls `GET /datasources`.
2. User can register a SQLite/SQLAlchemy datasource, register a local file path
   through `POST /datasources/from-path`, or upload CSV/Excel/optional Parquet
   through `POST /datasources/upload`.
3. User selects one datasource and frontend calls
   `POST /sessions/{session_id}/datasource`.
4. Optional: user clicks `Profile datasource`, which calls
   `POST /datasources/{datasource_id}/profile` and listens to the returned job
   events.
5. Later chat requests either omit `datasource_id` and use the session
   selection, or pass the same `datasource_id` explicitly.
6. If no datasource exists, analysis requests return a clarification message
   instead of executing SQL.
7. If multiple datasources exist and the session has not selected one, analysis
   requests ask the user to select a datasource first.

For file datasources, the Web UI should show the safe order: upload or register
the file, select the datasource, click `Profile datasource`, then ask a question.
When uploads fail, surface the API detail in user language for file too large,
unsupported extension, empty file, parser failure, missing Parquet dependency,
disabled local path mode, path traversal, or sensitive path rejection. Do not
display server-local full paths; show datasource id, original basename, table
name, row count, and column list only.

本文档描述前端如何编排当前 API、events、human confirmation 和 artifact 下载。

## 明确问题分析流程

1. 用户输入明确分析问题，例如 `Show monthly GMV trend`。
2. 前端调用 `POST /sessions/{session_id}/chat`，`command` 可省略或传 `none`。
3. 服务端创建 job，并按规则路由到 `direct_analysis`。
4. 前端保存返回的 `job_id`。
5. 前端打开 `GET /jobs/{job_id}/events/stream`，或轮询 `GET /jobs/{job_id}/events`。
6. 看到 `chart_ref` 时，只展示 artifact metadata 或占位卡片；需要渲染内容时调用 artifact API。
7. 看到 `done` 后调用 `GET /jobs/{job_id}` 读取最终状态。

最小请求：

```json
{
  "message": "Show monthly GMV trend",
  "command": "none"
}
```

## 开放探索流程

1. 用户选择开放探索，或输入包含 `explore` / `open analysis` 的消息。
2. 前端调用 `POST /sessions/{session_id}/chat`，也可以显式传 `command: "explore"`。
3. graph 生成候选主题、排序并执行 Top N 规则分析。
4. 若返回 `human_request`，前端展示确认或跳过确认选项。
5. 完成后读取 `final_state.analysis_package` 和 `final_response_text`。

最小请求：

```json
{
  "message": "Explore revenue opportunities",
  "command": "explore"
}
```

## 报告 / PPT / Excel / Dashboard 导出确认流程

导出工具不能由普通聊天直接执行。前端应先触发 outline 阶段，再由用户确认。

1. 用户要求导出，例如 `Create a PPT from this analysis`。
2. 前端调用 `POST /sessions/{session_id}/chat`，传入已有 `analysis_package`，`command` 可传 `report`。
3. 服务端生成 `report_outline` 或 dashboard outline，并写入 `human_request`。
4. job 状态变为 `waiting_for_human`，events 中出现 `human_request`。
5. 前端展示大纲和确认按钮。
6. 用户确认后，前端调用 `POST /jobs/{job_id}/approve`。
7. `approve` 请求中的 `command` 使用对应 confirm command。
8. 服务端走 confirm fast-path，复用已有 `report_outline`，不重新分析数据、不重新生成 outline。
9. 导出完成后，events 出现 `artifact_ref`。

确认命令：

- 报告：`report_confirm`
- PPT：`ppt_confirm`
- Excel：`excel_confirm`
- Dashboard：`dashboard_confirm`

确认请求：

```json
{
  "command": "ppt_confirm"
}
```

## Artifact 下载流程

events 和 `final_state` 中只应使用 artifact 引用。
Web UI 按 Charts、Reports、Excel、PPT、Dashboards 分组展示 artifact。

1. 从 `chart_ref` 或 `artifact_ref` event 读取 `artifact_id` / `artifact_ref`。
2. 调用 `GET /artifacts/{artifact_id}` 获取 metadata。
3. 根据 `mime_type` 决定展示或下载方式。
4. 调用 `GET /artifacts/{artifact_id}/content` 获取正文。
5. 下载失败时应向用户展示可读错误，不应静默失败或把失败当成空 artifact。

前端处理建议：

- `application/json`: 作为 chart spec 或 dashboard spec 解析。当前 Web UI
  可将 dashboard spec 渲染为 metric、chart、table 和 insight cards。
- `application/vnd.data-analysis-agent.chart+json`: 读取 chart artifact JSON，
  并在 Web UI 中渲染简单 line/bar SVG 预览；不支持的图表类型回退到有界 JSON 预览。
- `text/markdown`: 可直接渲染为报告预览。
- `text/html`: 在安全容器内展示。
- Excel / PPTX MIME: 作为文件下载。

不要从 events 中读取或缓存大文件正文。
Dashboard renderer 不新增后端 API，只使用已有 artifact metadata/content。

## Cancel 流程

1. 用户点击取消。
2. 前端调用 `POST /jobs/{job_id}/cancel`。
3. 服务端设置 cancel flag，并写入 `stopped` event。
4. 前端收到 `stopped` 后关闭 SSE。
5. 前端调用 `GET /jobs/{job_id}` 刷新状态，通常为 `cancelled`。

取消请求无 body。

## Human Request Approve 流程

`human_request` 表示流程需要用户确认或补充信息，不应只当普通文本处理。

前端建议状态机：

1. 事件流收到 `human_request`。
2. 保存 `request_id`、`request_type`、`prompt` 和可选 payload。
3. 在聊天流中渲染 assistant 确认卡片，并在输入框附近显示快捷按钮。
4. 如果 `human_request.options` 存在，按 options 渲染；否则显示默认
   `Yes / Confirm`、`No / Cancel`、`Report`、`Excel`、`PPT`、`Dashboard`。
5. 用户确认后调用 `POST /jobs/{job_id}/approve`。
6. approve command 必须与请求类型匹配，例如导出 PPT 使用 `ppt_confirm`。
7. approve 返回新的 `JobResponse`，前端继续监听 events 或读取最终状态。
8. 前端可在聊天流中追加“已确认生成 PPT/Excel/Dashboard”等用户选择摘要。

当前 approve 主要覆盖导出 fast-path；字段语义确认、SQL 风险确认等后续流程仍保留结构化占位。

## Minimal Client Example

`examples/client` 提供一个最小 Python 客户端，用来验证前端需要的 API 契约，不引入 UI 框架。

启动 API：

```bash
python scripts/run_api.py --runner-backend memory
```

提交 job、读取 events、解析 SSE、打印 artifact refs：

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --message "Show monthly GMV trend" \
  --stream
```

执行明确问题分析 + 报告导出确认：

```bash
python examples/client/demo_flow_client.py \
  --base-url http://127.0.0.1:8000 \
  --confirm-command excel_confirm
```

客户端会把发现的 artifact 引用归一为 `artifact:<id>`，并且只通过
`GET /artifacts/{artifact_id}/content` 下载 artifact 正文。


## Product LLM Config And Session Titles

The local Web UI can save a technical-preview LLM provider config through the API:

- GET /llm/config returns a sanitized provider config.
- POST /llm/config saves provider, model, base URL, enabled node defaults, and a local API key.
- POST /llm/test manually tests the saved or submitted provider config.
- PATCH /sessions/{session_id} renames a user-visible session.

The raw API key is never returned by status/config endpoints and must not appear in events,
session history, artifacts, or final responses. In this alpha, the key may be stored in the
local file configured by DATA_ANALYSIS_AGENT_LLM_CONFIG_PATH; the default
untime/ directory
is ignored by git. Session-level LLM settings still store only mode and enabled node aliases.
