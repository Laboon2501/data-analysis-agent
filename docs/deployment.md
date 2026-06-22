# Docker And Production Deployment

This project can run as a single-process memory backend for local demos or as a
Celery-backed distributed runtime for local integration and production-like
testing. The default remains memory backend, and real LLM providers stay off
unless explicitly configured.

## Images

The root `Dockerfile` builds one application image that can run either the API or
the worker command.

```bash
docker build -t data-analysis-agent:local .
```

The image installs dependencies from `pyproject.toml`, copies the application
source, and defaults to:

```bash
python scripts/run_api.py --host 0.0.0.0 --port 8000
```

## Memory Backend Compose

Use `docker-compose.yml` for a single API container with the memory backend.

```bash
docker compose up --build api
```

The service maps `127.0.0.1:8000`, uses the demo SQLite database at
`/app/demo/ecommerce_demo.sqlite`, and mounts the named volume `artifact_data` at
`/app/artifacts`.

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/runtime
```

Run the minimal client against it:

```bash
python examples/client/minimal_client.py --base-url http://127.0.0.1:8000 --stream
```

## Celery Backend Compose

Use `docker-compose.celery.yml` for API, worker, Redis, and Postgres.

```bash
docker compose -f docker-compose.celery.yml up --build
```

Included services:

- `api`: FastAPI app using `DATA_ANALYSIS_AGENT_RUNNER_BACKEND=celery`.
- `worker`: Celery worker started by `scripts/run_worker.py --execute`.
- `redis`: broker, result backend, cache/event store.
- `postgres`: checkpoint and session-store database example.

The API and worker share `artifact_data` at `/app/artifacts` and `upload_data`
at `/app/uploads`. This is required so artifact metadata/content and uploaded
file datasource conversions produced by a worker can be read by the API process.
Redis also carries the shared datasource registry snapshot and session
datasource selection used by Celery jobs, so file datasources registered through
the API can be profiled and analyzed by the worker.

Run a smoke after services are healthy:

```bash
python scripts/run_integration_smoke.py \
  --api-url http://127.0.0.1:8000 \
  --runner-backend celery \
  --sse \
  --datasource-kind file \
  --file-registration-mode upload \
  --file-path demo/ecommerce_orders_demo.csv \
  --file-table-name orders \
  --profile-datasource \
  --include-exploration \
  --include-exports
```

## Configuration

Start from `.env.example`. Do not commit `.env` or real secrets.

Core variables:

- `DATA_ANALYSIS_AGENT_RUNNER_BACKEND`: `memory` or `celery`.
- `DATA_ANALYSIS_AGENT_REDIS_URL`: Redis cache/event store URL.
- `DATA_ANALYSIS_AGENT_CELERY_BROKER_URL`: Celery broker URL.
- `DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND`: Celery result backend URL.
- `DATA_ANALYSIS_AGENT_CHECKPOINT_URL`: Postgres checkpoint SQLAlchemy URL.
- `DATA_ANALYSIS_AGENT_SESSION_STORE`: `memory`, `sqlite`, or `sqlalchemy`.
- `DATA_ANALYSIS_AGENT_SESSION_DB_URL`: SQLAlchemy URL for persistent session history.
- `DATA_ANALYSIS_AGENT_DATASOURCE_URL`: SQLite path or SQLAlchemy datasource URL.
- `DATA_ANALYSIS_AGENT_ARTIFACT_DIR`: shared artifact directory.
- `DATA_ANALYSIS_AGENT_UPLOAD_DIR`: shared upload directory for file datasources.
- `DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB`: upload size limit.
- `DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS`: keep `false` outside trusted
  local development.
- `DATA_ANALYSIS_AGENT_LLM_PROVIDER`, `DATA_ANALYSIS_AGENT_LLM_MODEL`,
  `DATA_ANALYSIS_AGENT_LLM_BASE_URL`, `DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV`:
  placeholders for optional LLM provider configuration.

Production deployments should inject secrets through the runtime platform secret
manager, not through committed files or image layers.

## Artifact And Upload Volumes

Artifacts and uploaded file bodies are intentionally stored outside
events/history. In distributed mode:

1. Worker writes the artifact through `FileArtifactStore`.
2. Events carry only `artifact_ref` and lightweight metadata.
3. API reads artifact metadata/content from the same mounted volume.
4. Clients call `GET /artifacts/{artifact_id}` and
   `GET /artifacts/{artifact_id}/content`.
5. File uploads are saved under `DATA_ANALYSIS_AGENT_UPLOAD_DIR`, converted to
   internal SQLite tables, and exposed through datasource metadata only.
6. Datasource metadata sent to clients uses basenames, masked URLs, row counts,
   and column names. It does not include full server-local upload paths or raw
   file bodies.

Do not mount artifact or upload volumes to a public static server unless access
control is added outside this project.

## Health Checks

Use:

- `GET /health`: process-local API status.
- `GET /health/runtime`: backend runtime configuration status.

For Celery, `/health/runtime` reports configuration readiness. It does not prove
that an external worker is online. Use platform-level worker process checks and
Celery monitoring for that.

## Security Boundaries

- Default backend remains `memory`.
- Default LLM strategy remains rule-based and does not call real providers.
- SQL execution still goes through `SQLGuard`; write statements are blocked.
- Export commands require explicit confirm commands.
- Chart/report/PPT/Excel/dashboard bodies stay in artifact storage, not events
  or chat history.
- MCP tools are opt-in through the adapter and ToolRegistry permissions.
- Do not expose Redis, Postgres, or artifact volumes directly to the public
  network.

## Operational Notes

- Use a persistent artifact volume for Celery deployments.
- Use Redis persistence or managed Redis if job event durability matters.
- Configure Postgres backups if checkpoints are business-critical.
- Terminate TLS at a reverse proxy or platform ingress.
- Keep API keys outside `.env.example`, docs, tests, and container images.
