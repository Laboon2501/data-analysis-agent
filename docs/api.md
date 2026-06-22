# API Contract

This document describes the FastAPI surface used by frontend integration and
local smoke scripts. Examples assume the default local base URL
`http://127.0.0.1:8000`.

## General Rules

- Requests and normal responses use JSON, except artifact content responses.
- Long-running work is represented as a `job_id`.
- Job progress can be read through the event list endpoint or the SSE stream.
- Chart HTML, dashboard specs, PPTX, Excel files, and report bodies are fetched
  only through artifact endpoints. Events and final responses carry references.
- The default backend is `memory`; `celery` is opt-in through config.

## GET /health

Returns process-local API health and the selected runner backend.

### Response

```json
{
  "status": "ok",
  "runner_backend": "memory"
}
```

## GET /health/runtime

Returns runtime configuration health for the active backend. The Celery backend
checks whether broker, Redis event stores, checkpoint URL, and artifact store
configuration are present; it does not require a live worker to answer.

### Memory Response

```json
{
  "status": "ok",
  "runner_backend": "memory",
  "worker": "local",
  "data_source_configured": true,
  "datasource_count": 1,
  "datasource_ids": ["ecommerce-demo-sqlite"],
  "llm_mode": "rule",
  "llm_provider": null,
  "llm_model": null,
  "llm_base_url_host": "api.openai.com",
  "llm_api_key_configured": false,
  "llm_enabled_nodes": [],
  "cache_store": "InMemoryCacheStore",
  "event_store": "InMemoryEventStore",
  "checkpoint_store": "InMemoryCheckpointStore",
  "artifact_store": "InMemoryArtifactStore",
  "session_store": {
    "store_type": "memory",
    "persistent": false,
    "db_url_masked": null,
    "ttl_days": null,
    "max_messages": null,
    "session_count": 0
  },
  "job_count": 0
}
```

### Celery Response

```json
{
  "status": "degraded",
  "runner_backend": "celery",
  "worker": "external",
  "broker_configured": false,
  "result_backend_configured": false,
  "redis_events_configured": false,
  "checkpoint_configured": false,
  "artifact_store": "FileArtifactStore",
  "artifact_dir": "artifacts",
  "queue_name": "data-analysis-agent",
  "task_name": "app.workers.celery_tasks.run_agent_job",
  "worker_online_checked": false
}
```

## GET /sessions

Returns user-visible chat sessions. This is not LangGraph checkpoint state; it is
only the UI/history view. The default store is memory; optional `sqlite` and
`sqlalchemy` stores persist the same response shape without artifact bodies.

### Response

```json
[
  {
    "session_id": "web-123",
    "title": "Show monthly GMV trend",
    "created_at": "2026-06-13T12:00:00Z",
    "updated_at": "2026-06-13T12:00:05Z",
    "datasource_id": "ecommerce-demo-sqlite",
    "llm_mode": "rule",
    "enabled_llm_nodes": [],
    "message_count": 2,
    "last_message_preview": "The time trend query returned 12 period rows.",
    "artifact_refs": ["artifact:chart-123"]
  }
]
```

## POST /sessions

Creates a user-visible session. The request body is optional.

### Request

```json
{
  "session_id": "web-123",
  "title": "Demo session"
}
```

## POST /sessions/cleanup

Manually runs the configured retention policy. This can delete sessions older
than `ttl_days` and trim oldest messages beyond `max_messages`. It never deletes
artifact files, checkpoints, or event logs.

### Request

```json
{
  "ttl_days": 30,
  "max_messages": 200,
  "exclude_session_ids": ["web-123"]
}
```

### Response

```json
{
  "deleted_sessions": 1,
  "trimmed_messages": 12,
  "remaining_sessions": 4
}
```

## GET /sessions/{session_id}

Returns one session record. Unknown sessions return `404`.

## DELETE /sessions/{session_id}

Deletes one user-visible session, its messages, and its job summaries from the
memory Session Store. It does not delete artifact files, checkpoints, or shared
event logs.

## GET /sessions/{session_id}/messages

Returns user-visible chat history for a session. Messages may contain artifact
refs, but never artifact bodies.

## POST /sessions/{session_id}/messages

Appends a visible message without invoking a graph. Normal chat requests write
messages automatically, so frontends usually do not need this endpoint.

### Request

```json
{
  "role": "user",
  "content": "hello",
  "job_id": null,
  "artifact_refs": [],
  "metadata": {}
}
```

## GET /sessions/{session_id}/jobs

Returns compact job summaries associated with a session. Summaries include
status, intent, command, error text if any, and artifact refs only.

## GET /llm/status

Returns process-level LLM runtime status for the active backend. The response may
say whether the configured API key environment variable exists, but it never
returns the API key value.

### Response

```json
{
  "mode": "rule",
  "provider": null,
  "model": null,
  "base_url_host": "api.openai.com",
  "base_url_masked": "https://api.openai.com/v1",
  "api_key_configured": false,
  "enabled_nodes": [],
  "last_llm_call_count": 0,
  "last_llm_error_count": 0,
  "last_llm_fallback_count": 0,
  "last_llm_json_invalid_count": 0
}
```

## GET /sessions/{session_id}/llm

Returns the effective session-level LLM mode, enabled node aliases, provider
metadata, and last-job LLM event counters. Supported modes are `rule`,
`fake_llm`, and `real_llm`. Default mode is `rule`.

## POST /sessions/{session_id}/llm

Sets the session-level LLM mode and enabled node aliases. This endpoint accepts
only narrow aliases: `router`, `planner`, `sql_drafter`, and `insight_writer`.
`real_llm` requires the backend environment to provide a model and API key env
var; the Web UI cannot upload or save keys.

### Request

```json
{
  "mode": "fake_llm",
  "enabled_nodes": ["planner", "sql_drafter", "insight_writer"]
}
```

### Error Example

```json
{
  "detail": "real_llm mode requires API key environment variable: OPENAI_API_KEY"
}
```

## GET /datasources

Returns registered datasource metadata. Responses hide connection-string
passwords and do not include API keys.

### Response

```json
[
  {
    "datasource_id": "ecommerce-demo-sqlite",
    "name": "Ecommerce demo SQLite",
    "kind": "sqlite",
    "url": null,
    "db_path": "demo/ecommerce_demo.sqlite",
    "status": "available",
    "created_at": "2026-06-13T12:00:00Z",
    "last_profiled_at": null,
    "schema_hash": null,
    "error_message": null
  }
]
```

## POST /datasources

Registers a SQLite or SQLAlchemy datasource. File datasources use the dedicated
`from-path` or `upload` endpoints below so the API can enforce file type, size,
and path-safety checks.

### Request

```json
{
  "datasource_id": "local-sqlite",
  "name": "Local SQLite",
  "kind": "sqlite",
  "db_path": "demo/ecommerce_demo.sqlite",
  "url": null
}
```

For SQLAlchemy datasources, use `kind: "sqlalchemy"` and `url`. Passwords are
masked in API responses.

## POST /datasources/from-path

Registers a local CSV, Excel xlsx, or Parquet file path as a file datasource.
This endpoint is disabled by default and requires
`DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS=true`, because it can read local
filesystem paths. It returns safe metadata only: basename, table name, row
count, columns, size, and status. It does not return original file contents or
internal converted SQLite paths.
The API rejects sensitive paths, path traversal attempts, unsupported
extensions, oversized files, empty files, parse failures, and Parquet files when
the optional dependency is unavailable.

### Request

```json
{
  "path": "D:\\data\\orders.csv",
  "datasource_id": "orders-file",
  "name": "Orders CSV",
  "table_name": "orders"
}
```

## POST /datasources/upload

Uploads a CSV, Excel xlsx, or Parquet file through multipart form data, stores
it in `DATA_ANALYSIS_AGENT_UPLOAD_DIR`, converts it to an internal SQLite table,
and registers it as a file datasource. Upload size is limited by
`DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB`. Unsupported extensions, path-traversal
filenames, empty files, parser failures, missing Parquet dependency, and
sensitive environment filenames are rejected. Responses never include server
upload paths or converted SQLite paths.

### Form Fields

- `file`: required uploaded file.
- `datasource_id`: optional datasource id. If omitted, one is generated.
- `name`: optional display name.
- `table_name`: optional SQL table name used for the converted file.

## GET /datasources/{datasource_id}

Returns one datasource metadata record. Unknown datasources return `404`.

## POST /datasources/{datasource_id}/profile

Submits a Context Manager job for the selected datasource and returns the normal
`JobResponse`. The datasource registry stores `last_profiled_at` and
`schema_hash` after a successful profile.

## POST /sessions/{session_id}/datasource

Sets the datasource used by later chat jobs in the session.

### Request

```json
{
  "datasource_id": "ecommerce-demo-sqlite"
}
```

### Response

```json
{
  "session_id": "session-1",
  "datasource_id": "ecommerce-demo-sqlite",
  "datasource": {
    "datasource_id": "ecommerce-demo-sqlite",
    "name": "Ecommerce demo SQLite",
    "kind": "sqlite",
    "status": "available"
  }
}
```

## GET /sessions/{session_id}/datasource

Returns the session datasource selection. If exactly one datasource is
registered, the memory backend can return that datasource as the effective
selection. If multiple datasources exist and the session has not selected one,
`datasource_id` is `null`.

## POST /sessions/{session_id}/chat

Creates a job and routes it to the appropriate graph based on `message` and
`command`.

### Request

```json
{
  "message": "Show monthly GMV trend",
  "datasource_id": "demo",
  "command": "none",
  "analysis_package": null,
  "report_outline": null
}
```

Fields:

- `message`: user message.
- `datasource_id`: optional datasource identifier.
- `command`: optional command. Common values are `none`, `profile`, `analyze`,
  `explore`, `report`, `ppt_confirm`, `report_confirm`, `excel_confirm`, and
  `dashboard_confirm`.
- `analysis_package`: existing package for report/export flows.
- `report_outline`: existing outline for confirm fast-path flows.

### Response

```json
{
  "job_id": "job-123",
  "session_id": "session-1",
  "status": "completed",
  "intent": "direct_analysis",
  "command": "analyze",
  "needs_human": false,
  "final_response_text": "Analysis completed.",
  "error_message": null,
  "final_state": {
    "session_id": "session-1",
    "job_id": "job-123",
    "user_message": "Show monthly GMV trend"
  },
  "created_at": "2026-06-13T12:00:00Z",
  "updated_at": "2026-06-13T12:00:01Z"
}
```

## GET /jobs/{job_id}

Returns the current job status and latest final state.

### Response

```json
{
  "job_id": "job-123",
  "session_id": "session-1",
  "status": "waiting_for_human",
  "intent": "report_export",
  "command": "report",
  "needs_human": true,
  "final_response_text": "Please confirm the report outline.",
  "error_message": null,
  "final_state": {
    "human_request": {
      "request_type": "report_confirm",
      "prompt": "Confirm before exporting."
    }
  },
  "created_at": "2026-06-13T12:00:00Z",
  "updated_at": "2026-06-13T12:00:01Z"
}
```

Unknown jobs return `404`.

## GET /jobs/{job_id}/events

Returns recorded job events as a finite JSON array.

### Response

```json
[
  {
    "event_id": "event-1",
    "event_type": "node_start",
    "session_id": "session-1",
    "job_id": "job-123",
    "node_name": "draft_sql",
    "tool_name": null,
    "message": "Node started.",
    "payload": {},
    "created_at": "2026-06-13T12:00:00Z"
  }
]
```

Unknown jobs return `404`.

## GET /jobs/{job_id}/events/stream

Streams job events as Server-Sent Events until a terminal `done`, `error`, or
`stopped` event appears.

### Response Headers

```text
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

### SSE Frame

```text
event: node_start
data: {"event_id":"event-1","event_type":"node_start","session_id":"session-1","job_id":"job-123","node_name":"draft_sql","tool_name":null,"message":"Node started.","payload":{},"created_at":"2026-06-13T12:00:00Z"}
```

Known large payload keys such as rendered chart HTML or file bytes are omitted
from stream data.

## POST /jobs/{job_id}/approve

Resumes a waiting human-in-the-loop job with an explicit confirm command. Report,
PPT, Excel, and dashboard exports use this confirm fast-path and reuse the
existing `analysis_package` and `report_outline`.

### Request

```json
{
  "command": "ppt_confirm"
}
```

Allowed confirm commands:

- `report_confirm`
- `ppt_confirm`
- `excel_confirm`
- `dashboard_confirm`

Unknown jobs return `404`; invalid commands or states return `400`.

## POST /jobs/{job_id}/cancel

Sets the cancel flag and records a `stopped` event.

### Response

```json
{
  "job_id": "job-123",
  "session_id": "session-1",
  "status": "cancelled",
  "intent": "report_export",
  "command": "report",
  "needs_human": true,
  "final_response_text": "Please confirm the report outline.",
  "error_message": null,
  "final_state": {},
  "created_at": "2026-06-13T12:00:00Z",
  "updated_at": "2026-06-13T12:00:02Z"
}
```

Unknown jobs return `404`.

## GET /artifacts/{artifact_id}

Returns artifact metadata only.

### Response

```json
{
  "artifact_id": "artifact-123",
  "artifact_ref": "artifact:artifact-123",
  "metadata": {
    "artifact_type": "chart",
    "title": "Monthly GMV trend",
    "created_at": "2026-06-13T12:00:00Z"
  },
  "mime_type": "application/json",
  "content_type": "json"
}
```

Unknown artifacts return `404`.

## GET /artifacts/{artifact_id}/content

Returns artifact content using the artifact metadata `mime_type`.

Common mime types:

- `application/json`: dashboard spec or generic JSON artifact.
- `application/vnd.data-analysis-agent.chart+json`: lightweight chart artifact JSON.
- `text/markdown`: lightweight report.
- `text/html`: HTML report.
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`: Excel.
- `application/vnd.openxmlformats-officedocument.presentationml.presentation`: PPTX.

Dashboard rendering still uses only these artifact endpoints: the Web UI reads
dashboard metadata, fetches dashboard JSON content, and then fetches referenced
chart artifacts as needed. Events and chat history carry only artifact refs.

Unknown artifacts return `404`.

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
