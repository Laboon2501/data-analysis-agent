# Eval / Regression Suite

This directory provides offline regression evals for the LangGraph-based
Data-Analysis-Agent. The default suite uses SQLite fixtures and rule strategy.
It does not call real LLM providers, Redis, Postgres, Celery, or MCP servers.

## Structure

```text
evals/
  cases/
    direct_analysis_cases.jsonl
    open_exploration_cases.jsonl
    context_profile_cases.jsonl
    report_export_cases.jsonl
    schema_qa_cases.jsonl
    router_cases.jsonl
    demo_ecommerce_cases.jsonl
    llm_eval_cases.jsonl
  metrics.py
  runner.py
  README.md
```

## Case Schema

Each JSONL line is one eval case:

- `case_id`: stable case id.
- `tags`: optional tags for focused LLM eval runs, such as `router`, `sql`,
  `file-datasource`, or `export`.
- `datasource_fixture`: offline datasource fixture such as `sqlite_orders` or
  `sqlite_ecommerce_demo`. Optional LLM evals also include
  `file_ecommerce_orders_csv`.
- `user_message`: user question or task.
- `expected_intent`: expected workflow intent.
- `expected_sql_contains`: SQL fragments expected in generated SQL.
- `expected_tables`: expected referenced or profiled tables.
- `expected_metrics`: expected metric fields.
- `expected_chart_type`: expected chart type, when applicable.
- `expected_artifact_types`: expected export artifact types.
- `must_not_contain`: text that must not appear in events, final response, or SQL.
- `notes`: human-readable case notes.

## Metrics

Pass/fail metrics:

- `intent_accuracy`
- `sql_table_match`
- `sql_field_match`
- `sql_table_field_match`
- `sql_safety`
- `result_non_empty_rate`
- `chart_type_match`
- `artifact_generation`
- `router_intent_accuracy`
- `no_sql_for_chat`
- `no_react_tool_free_call_violation`
- `no_large_payload_in_events_history`

Diagnostic stats:

- `llm_call_count`
- `llm_error_count`
- `llm_fallback_count`
- `llm_json_invalid_count`
- `sql_guard_block_count`
- `generated_sql_valid_rate`
- `fallback_rate`
- `json_invalid_rate`
- `intent_accuracy`
- `router_accuracy`
- `sql_table_match_rate`
- `sql_field_match_rate`
- `artifact_pass_rate`
- `no_sql_for_chat_pass_rate`

Each result also includes bounded failure details: expected fields, actual
intent, generated SQL, SQL validation, LLM observability events, fallback
reasons, and structured runtime errors. Prompt content, API keys, artifact
bodies, and uploaded file contents are not stored in eval details.

`no_large_payload_in_events_history` checks events and final responses only. Chart
HTML, Excel/PPTX bytes, dashboard specs, and report bodies must remain in the
artifact store / artifact API path.

## Default Offline Runs

Run the default regression suite:

```bash
python -m evals.runner
```

The default suite includes `router_cases.jsonl` as `router-only` checks. These
cases validate app-level intent routing, including schema QA versus open
exploration, without requiring SQL generation.

Run a specific case file:

```bash
python -m evals.runner --case-file evals/cases/direct_analysis_cases.jsonl
```

Run a focused optional LLM case subset by tag:

```bash
python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --tag router

python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --tag file-datasource
```

Write summary JSON:

```bash
python -m evals.runner --output eval-summary.json
```

Use `FakeLLMClient` to exercise LLM fallback paths without network:

```bash
python -m evals.runner --strategy fake-llm
```

## Optional Real LLM Eval

Real LLM eval is opt-in and never runs in default pytest or CI. It requires both:

1. `--strategy real-llm`
2. Explicit `--llm-nodes`, such as `sql_drafter` or `insight_writer`

Example using environment-backed config:

```bash
export DATA_ANALYSIS_AGENT_LLM_PROVIDER=openai_compatible
export DATA_ANALYSIS_AGENT_LLM_MODEL=your-model-name
export DATA_ANALYSIS_AGENT_LLM_BASE_URL=https://your-provider.example.com/v1
export DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV=YOUR_PROVIDER_API_KEY
export YOUR_PROVIDER_API_KEY=replace-with-local-secret

python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --strategy real-llm \
  --tag sql \
  --llm-nodes planner sql_drafter insight_writer
```

OpenAI-compatible example:

```bash
python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --strategy real-llm \
  --tag sql \
  --llm-nodes sql_drafter insight_writer \
  --llm-provider openai_compatible \
  --llm-model gpt-4.1-mini \
  --llm-base-url https://api.openai.com/v1 \
  --llm-api-key-env OPENAI_API_KEY
```

DeepSeek/OpenAI-compatible style example:

```bash
python -m evals.runner \
  --case-file evals/cases/llm_eval_cases.jsonl \
  --strategy real-llm \
  --tag router \
  --tag sql \
  --llm-nodes planner sql_drafter insight_writer \
  --llm-provider openai_compatible \
  --llm-model deepseek-chat \
  --llm-base-url https://api.deepseek.com/v1 \
  --llm-api-key-env DEEPSEEK_API_KEY
```

Do not write real API keys into source files, test fixtures, `.env.example`, or
committed docs.

## Reading LLM Eval Metrics

- `fallback_rate`: `llm_fallback_count / llm_call_count`. A high value means the
  rule fallback path is preserving execution but the selected model/prompt is
  unstable.
- `json_invalid_rate`: `llm_json_invalid_count / llm_call_count`. Non-zero values
  mean the model ignored the required JSON contract.
- `sql_guard_block_count`: number of generated SQL strings rejected by SQLGuard.
  This should be investigated, but blocked SQL is still safer than execution.
- `generated_sql_valid_rate`: read-only SQL validity after guard checks.
- `no_sql_for_chat_pass_rate`: chat/help/invalid inputs that correctly avoided
  SQL generation.
- `artifact_pass_rate`: export cases that produced the expected artifact types
  without placing file bodies into events or history.

## Convenience Script

`scripts/run_llm_eval.py` wraps the same real-LLM eval path and prints a compact
manual report with failed cases, fallback counts, and SQLGuard stats.

```bash
python scripts/run_llm_eval.py \
  --tag sql \
  --llm-node sql_drafter \
  --llm-node insight_writer \
  --model your-model-name \
  --base-url https://your-provider.example.com/v1 \
  --api-key-env YOUR_PROVIDER_API_KEY
```

The script defaults to `evals/cases/llm_eval_cases.jsonl` and is not used by
pytest or CI.

## Current Coverage

- Context Manager: schema/profile construction and core field detection.
- SQL / Direct Analysis: summary, time trend, and TopN.
- Optional LLM Eval: router chat/help/no-SQL, planner/sql-drafter trend,
  TopN, dimension comparison, SQLGuard safety prompts, insight fallback, and
  CSV file datasource trend/TopN.
- Open Exploration: candidate topics, ranking, and TopN automatic analysis.
- Report Export: report / Excel / PPT / Dashboard confirm fast-path artifacts.

## Limits

- Default eval does not cover real LLM provider quality.
- Default eval does not require Redis/Postgres/Celery.
- It does not assess complex visualization rendering quality.
- It does not assess visual design quality of exported files.
