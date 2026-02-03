# Agent Server Specification (Single-File FastAPI, Minimal First Iteration)

## 1) Goal and Approach

Build a single FastAPI application (`main.py`) that includes:
- Classic LangChain tool-calling agent
- API endpoints for datasets/chat/runs
- Sandboxed SQL execution via the existing runner container
- Static web UI served by the same FastAPI app
- Streaming support (SSE) for chat progress/result updates

This intentionally avoids LangGraph server dependency and keeps the footprint small for fast iteration and interview clarity.

---

## 2) High-Level Architecture

Single process, single app:

1. Browser UI (`GET /`) -> FastAPI static HTML/JS
2. UI sends chat requests (`POST /chat` or `POST /chat/stream`)
3. LangChain agent in-process decides tool usage
4. Tools validate/compile plan or validate SQL
5. Server executes SQL only via sandboxed runner container
6. Server persists run capsule to SQLite
7. Server returns result payload (+ streaming events for SSE)

**Security boundary:** Model output is untrusted; execution is always via runner sandbox.

---

## 3) Single-File Layout (`main.py`)

Recommended internal ordering:

1. Imports + config/env loading
2. Pydantic API models
3. Dataset registry loading helpers
4. SQL policy validation helpers
5. QueryPlan compile/validation adapters
6. Runner execution helper (Docker subprocess/SDK)
7. Capsule persistence helpers (SQLite)
8. LangChain tools
9. Agent constructor (lazy singleton)
10. FastAPI routes
11. Static UI route (`GET /`)

---

## 4) Required Endpoints

### Health and Metadata
- `GET /healthz`
  - Returns service readiness and key dependency status.

- `GET /datasets`
  - Returns dataset metadata from `datasets/registry.json`:
    - id, name, description, prompts, version_hash, files summary.

- `GET /datasets/{id}/schema`
  - Returns schema and optional sample rows for selected dataset.

### Chat
- `POST /chat` (non-streaming baseline)
  - Input: `{ dataset_id, thread_id?, message }`
  - Output:
    - `assistant_message`
    - `run_id`
    - `status`
    - `result` (`columns`, `rows`, `row_count`, `exec_time_ms`, `error`)
    - `details` (`query_mode`, `plan_json`, `compiled_sql`, `dataset_id`)

- `POST /chat/stream` (SSE)
  - Emits events in sequence:
    - `status` (`planning`)
    - `status` (`validating`)
    - `status` (`executing`)
    - `result` (final structured payload)
    - `done`

### Runs / Audit
- `GET /runs/{run_id}`
  - Returns persisted run capsule by ID.

---

## 5) Agent Tools (Classic LangChain Pattern)

Expose exactly these tools in first iteration:

1. `list_datasets()`
2. `get_dataset_schema(dataset_id)`
3. `execute_query_plan(dataset_id, plan_json)`
4. `execute_sql(dataset_id, sql)`
5. `get_run_status(run_id)`

Tool behavior:
- `execute_query_plan`:
  - Validate plan schema -> compile to SQL -> validate SQL policy -> run in sandbox.
- `execute_sql`:
  - Validate SQL policy -> run in sandbox.
- Both create run capsules and return structured results.

---

## 6) Query and Execution Rules

### Query policy
- Default agent behavior: produce QueryPlan JSON.
- If user explicitly asks for SQL, allow SQL mode.
- Never claim execution until runner result is available.

### Validation
- QueryPlan: use existing Pydantic models.
- Compilation: deterministic existing compiler.
- SQL policy: read-only only; reject DDL/DML/admin/exfil-prone constructs.

### Execution
- Runner invoked with hardened flags:
  - `--network none`
  - `--read-only`
  - `--pids-limit 64`
  - `--memory 512m --cpus 0.5`
  - `--tmpfs /tmp:rw,noexec,nosuid,size=64m`
  - datasets mounted read-only at `/data`

---

## 7) Error Model (Standardized)

Use standardized error types end-to-end:
- `VALIDATION_ERROR`
- `SQL_POLICY_VIOLATION`
- `RUNNER_TIMEOUT`
- `RUNNER_RESOURCE_EXCEEDED`
- `RUNNER_INTERNAL_ERROR`

UI-facing messages should be human-readable but preserve machine-parseable error types.

---

## 8) Run Capsule Persistence (SQLite)

Single table `run_capsules`:
- `run_id` (PK)
- `created_at`
- `dataset_id`
- `dataset_version_hash`
- `question`
- `query_mode` (`plan`/`sql`)
- `plan_json`
- `compiled_sql`
- `status`
- `result_json`
- `error_json`
- `exec_time_ms`

Persistence is required for `/runs/{run_id}` and auditability.

---

## 9) Static UI (Same FastAPI App)

Minimal UI requirements:
- Dataset selector
- Suggested prompts per dataset
- Chat input + send button
- Streamed progress/status display
- Result table rendering
- Details panel:
  - plan JSON
  - compiled SQL
  - run status/runtime
  - run_id

Transport:
- Non-streaming via `POST /chat`
- Streaming via `POST /chat/stream` (SSE)

---

## 10) Configuration (Environment Variables)

Minimum required:
- `ANTHROPIC_API_KEY` (or chosen LLM provider key)
- `RUNNER_IMAGE` (e.g., `csv-analyst-runner:test`)
- `RUN_TIMEOUT_SECONDS`
- `MAX_ROWS`
- `DATASETS_DIR`
- `CAPSULE_DB_PATH`
- `LOG_LEVEL`

---

## 11) TDD Implementation Plan (Minimal-First)

### Phase A: Deterministic Core (No LLM)
Write failing tests first for:
1. Dataset endpoints (`/datasets`, `/datasets/{id}/schema`)
2. SQL policy validator
3. Runner adapter execution success/failure
4. Capsule persistence and retrieval

### Phase B: Tool Layer
Write tool contract tests first:
1. `execute_query_plan` happy path and validation failure
2. `execute_sql` policy rejection and timeout mapping
3. `get_run_status` capsule retrieval

### Phase C: Chat API
Write API tests first:
1. `POST /chat` returns structured payload
2. Error taxonomy mapped correctly
3. `POST /chat/stream` emits expected event sequence

### Phase D: UI Smoke
Write lightweight smoke tests:
1. UI loads from `GET /`
2. Basic chat request works end-to-end
3. One golden query per dataset passes through API

---

## 12) Acceptance for First Iteration

Must pass:
1. `POST /chat` works for representative query on each dataset.
2. `POST /chat/stream` streams status + final result.
3. Runner-only execution enforced (no direct SQL in server process).
4. Error model standardized and stable.
5. Run capsule retrievable via `GET /runs/{run_id}`.
6. Static UI demonstrates end-to-end query flow with details panel.

