# Agent Server

Single-file FastAPI server for CSV Analyst Chat.

## What Exists Now

- `app/main.py` contains the initial full server slice:
  - `GET /healthz`
  - `GET /datasets`
  - `GET /datasets/{dataset_id}/schema`
  - `POST /chat`
  - `POST /chat/stream` (SSE)
  - `GET /runs/{run_id}`
  - `GET /` (minimal static UI)
- QueryPlan DSL + compiler live in:
  - `app/models/query_plan.py`
  - `app/validators/compiler.py`
- Run capsules are persisted to SQLite (`CAPSULE_DB_PATH`).

## Runner Contract

The server compiles/validates upstream and sends SQL to runner.

Runner input contract (stdin JSON):
- `dataset_id`
- `files[]` (`name`, `/data/...` path)
- `sql`
- `timeout_seconds`
- `max_rows`

Runner returns JSON result/error; server normalizes this into API responses and capsules.

## Environment

The app auto-loads `.env` from:
1. repository root
2. current working directory

Create `/home/juancho/projects/adoptaisandbox/.env` from root `.env.example`.

Key vars:
- `LLM_PROVIDER` (`auto|openai|anthropic`)
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `DATASETS_DIR`, `CAPSULE_DB_PATH`
- `RUNNER_IMAGE`, `RUN_TIMEOUT_SECONDS`, `MAX_ROWS`, `LOG_LEVEL`

## Run Locally

From repo root:

```bash
make run-agent-dev
```

or directly:

```bash
uvicorn app.main:app --app-dir agent-server --host 0.0.0.0 --port 8000 --reload
```

Then open `http://localhost:8000`.

## Tests

```bash
# Server integration
make test-agent-server

# QueryPlan/compiler unit tests
pytest tests/unit/test_query_plan.py tests/unit/test_compiler.py -q
```

## QueryPlan Demo

```bash
cd agent-server
python3 demo_query_plan.py
```

This demonstrates the DSL and deterministic SQL compilation path used by the server when plan mode is selected.
