# Minimal API Client Examples

These examples are tiny Python clients for frontend/backend integration checks.
They use only the Python standard library and do not require a real LLM, Redis,
Celery, Postgres, or Docker.

Start the local API first:

```bash
python scripts/create_demo_db.py --output demo/ecommerce_demo.sqlite
python scripts/run_api.py --runner-backend memory
```

## minimal_client.py

Submit one job, poll status, inspect events, optionally read SSE, and print
artifact references.

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --session-id client-example \
  --message "Show monthly GMV trend" \
  --stream
```

Cancel example:

```bash
python examples/client/minimal_client.py \
  --base-url http://127.0.0.1:8000 \
  --message "Prepare a report" \
  --command report \
  --cancel
```

The client supports:

- `POST /sessions/{session_id}/chat`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/events`
- `GET /jobs/{job_id}/events/stream`
- `POST /jobs/{job_id}/approve`
- `POST /jobs/{job_id}/cancel`
- `GET /artifacts/{artifact_id}`
- `GET /artifacts/{artifact_id}/content`

It parses SSE frames and normalizes discovered artifact references to
`artifact:<id>` for display. Artifact body downloads only happen through the
artifact API.

## demo_flow_client.py

Run a direct analysis, create a report outline, approve one export command, and
download artifact metadata/content.

```bash
python examples/client/demo_flow_client.py \
  --base-url http://127.0.0.1:8000 \
  --confirm-command excel_confirm
```

Other confirm commands:

- `report_confirm`
- `ppt_confirm`
- `dashboard_confirm`

The output includes job IDs, event types, final response text, artifact refs,
and downloaded artifact byte sizes. It is intentionally not a frontend UI.
