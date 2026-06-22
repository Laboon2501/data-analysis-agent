# Event Contract

`AgentEvent` 是 job 进度、节点状态、LLM 观测和 artifact 引用的统一事件结构。
事件可通过 `GET /jobs/{job_id}/events` 一次性读取，也可通过
`GET /jobs/{job_id}/events/stream` 以 SSE 读取。

## 通用结构

```json
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
```

约束：

- `event_type` 必须是本文档列出的类型。
- `payload` 只放结构化小对象。
- events 不包含完整图表 HTML、Dashboard JSON、大文件正文、二进制内容或 API key。
- 图表、Excel、PPT、报告、Dashboard spec 正文必须通过 artifact API 获取。

## node_start

节点开始执行。

```json
{
  "event_id": "event-node-start",
  "event_type": "node_start",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "draft_sql",
  "tool_name": null,
  "message": "Node started.",
  "payload": {},
  "created_at": "2026-06-13T12:00:00Z"
}
```

## node_end

节点执行结束。

```json
{
  "event_id": "event-node-end",
  "event_type": "node_end",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "draft_sql",
  "tool_name": null,
  "message": "Node completed.",
  "payload": {"retry_count": 0},
  "created_at": "2026-06-13T12:00:01Z"
}
```

## tool_start

节点开始调用受控工具。事件只记录工具名、节点名和小型 metadata。

```json
{
  "event_id": "event-tool-start",
  "event_type": "tool_start",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "execute_sql",
  "tool_name": "query_data",
  "message": "Tool started.",
  "payload": {"category": "sql"},
  "created_at": "2026-06-13T12:00:01Z"
}
```

## tool_end

受控工具调用结束。payload 不包含 SQL result 大表、文件正文或渲染后的图表 HTML。

```json
{
  "event_id": "event-tool-end",
  "event_type": "tool_end",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "execute_sql",
  "tool_name": "query_data",
  "message": "Tool completed.",
  "payload": {"row_count": 12},
  "created_at": "2026-06-13T12:00:02Z"
}
```

## text_delta

面向前端展示的短文本增量或最终短回复片段。不得携带 artifact 正文。

```json
{
  "event_id": "event-text",
  "event_type": "text_delta",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "final_response",
  "tool_name": null,
  "message": "Analysis completed.",
  "payload": {"text": "The time trend query returned 12 period rows."},
  "created_at": "2026-06-13T12:00:03Z"
}
```

## error

节点、工具或 job 失败。

```json
{
  "event_id": "event-error",
  "event_type": "error",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "validate_sql",
  "tool_name": null,
  "message": "SQL validation failed.",
  "payload": {
    "code": "sql_validation_failed",
    "summary": "Only SELECT statements are allowed."
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## done

job 成功完成。SSE 收到该事件后应结束读取。

```json
{
  "event_id": "event-done",
  "event_type": "done",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": null,
  "tool_name": null,
  "message": "Job completed.",
  "payload": {},
  "created_at": "2026-06-13T12:00:03Z"
}
```

## stopped

job 被取消或 cancel flag 在节点执行前生效。SSE 收到该事件后应结束读取。

```json
{
  "event_id": "event-stopped",
  "event_type": "stopped",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": null,
  "tool_name": null,
  "message": "Job cancellation requested.",
  "payload": {"status": "cancelled"},
  "created_at": "2026-06-13T12:00:02Z"
}
```

## chart_ref

图表 artifact 已生成。事件只包含引用和 metadata，不包含图表正文。

```json
{
  "event_id": "event-chart",
  "event_type": "chart_ref",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "generate_chart_artifact",
  "tool_name": "generate_chart",
  "message": "Chart artifact generated.",
  "payload": {
    "artifact_id": "chart-123",
    "artifact_ref": "artifact:chart-123",
    "mime_type": "application/json",
    "metadata": {
      "artifact_type": "chart",
      "title": "Monthly revenue trend"
    }
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## artifact_ref

报告、Excel、PPT 或 Dashboard artifact 已生成。事件只包含引用，不包含正文。

```json
{
  "event_id": "event-artifact",
  "event_type": "artifact_ref",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "export_file",
  "tool_name": "export_excel",
  "message": "Export artifact generated.",
  "payload": {
    "artifact_id": "excel-123",
    "artifact_ref": "artifact:excel-123",
    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "metadata": {
      "report_type": "excel",
      "source_analysis_package_id": "package-123"
    }
  },
  "created_at": "2026-06-13T12:00:03Z"
}
```

## human_request

工作流需要用户确认或补充信息。

```json
{
  "event_id": "event-human",
  "event_type": "human_request",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "request_report_confirm",
  "tool_name": null,
  "message": "Report outline requires confirmation.",
  "payload": {
    "request_id": "human-123",
    "request_type": "report_confirm",
    "prompt": "Confirm before exporting the report."
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

前端收到该事件后应展示确认 UI，并在用户确认时调用 `POST /jobs/{job_id}/approve`。

## usage

可选的轻量用量统计事件，例如 LLM token 或节点耗时。不得包含完整 prompt、API key 或 provider 原始响应。

```json
{
  "event_id": "event-usage",
  "event_type": "usage",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "generate_insight",
  "tool_name": null,
  "message": "Usage metadata recorded.",
  "payload": {
    "provider": "openai_compatible",
    "model": "example-model",
    "input_tokens": 120,
    "output_tokens": 80
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## llm_start

启用 LLM strategy 的节点开始调用模型。

```json
{
  "event_id": "event-llm-start",
  "event_type": "llm_start",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "generate_insight",
  "tool_name": null,
  "message": "LLM call started.",
  "payload": {
    "provider": "openai_compatible",
    "model": "example-model",
    "prompt_name": "insight_writer"
  },
  "created_at": "2026-06-13T12:00:01Z"
}
```

## llm_end

LLM 调用成功结束。payload 不保存完整 prompt 或超长原始输出。

```json
{
  "event_id": "event-llm-end",
  "event_type": "llm_end",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "generate_insight",
  "tool_name": null,
  "message": "LLM call completed.",
  "payload": {
    "provider": "openai_compatible",
    "model": "example-model",
    "output_chars": 240
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## llm_error

LLM provider 错误、超时或适配层错误。

```json
{
  "event_id": "event-llm-error",
  "event_type": "llm_error",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "draft_sql",
  "tool_name": null,
  "message": "LLM call failed.",
  "payload": {
    "provider": "openai_compatible",
    "model": "example-model",
    "error_type": "timeout",
    "error_summary": "Provider timed out after configured timeout."
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## llm_fallback

LLM 节点失败后已切回 rule strategy，流程继续。

```json
{
  "event_id": "event-llm-fallback",
  "event_type": "llm_fallback",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "draft_sql",
  "tool_name": null,
  "message": "Falling back to rule strategy.",
  "payload": {
    "fallback_reason": "llm_error",
    "provider": "openai_compatible",
    "model": "example-model",
    "error_summary": "Provider timed out after configured timeout.",
    "fallback_to_rule": true
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```

## llm_json_invalid

LLM 返回内容无法解析为合法 JSON object。

```json
{
  "event_id": "event-llm-json",
  "event_type": "llm_json_invalid",
  "session_id": "session-1",
  "job_id": "job-123",
  "node_name": "generate_insight",
  "tool_name": null,
  "message": "LLM output was not valid JSON.",
  "payload": {
    "provider": "openai_compatible",
    "model": "example-model",
    "error_type": "JSON_INVALID",
    "error_summary": "Expected a JSON object."
  },
  "created_at": "2026-06-13T12:00:02Z"
}
```
