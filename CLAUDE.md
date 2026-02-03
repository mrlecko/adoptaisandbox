# CLAUDE.md — CSV Analyst Chat

Context file for AI assistants. Reflects the actual state of the codebase as of 2026-02-03.

---

## Quick Bootstrap (read this first)

```bash
# Tests require the agent-server venv. System Python WILL fail.
agent-server/.venv/bin/pytest tests/unit/ -q

# Start the server (the primary dev command)
make run-agent-dev

# Server runs on http://localhost:8000
# Static UI is at / , API docs at /docs
```

**If you just finished reading this file and need to orient:** the project is a working end-to-end system. Phases 0 and 1 are complete. Don't try to re-implement datasets, the runner, the executor layer, or the agent. The current work is Phase 2 hardening and any task the user assigns.

---

## Project Identity

- **Name:** CSV Analyst Chat
- **What it does:** Natural language → SQL/Python → sandboxed execution against CSV datasets → results
- **Stage:** Phase 2 (Phase 0 + 1 complete; production hardening in progress)
- **LLM:** OpenAI (default, `gpt-4o-mini`) or Anthropic (`claude-3-5-sonnet`). Resolution order: OpenAI first when `LLM_PROVIDER=auto`

---

## Architecture

```
Browser (static UI)
    │  GET /          – chat interface
    │  POST /chat     – send message (blocking)
    │  POST /chat/stream – send message (SSE streaming)
    ▼
FastAPI Agent Server  (agent-server/app/main.py)
    ├── LangGraph react agent  (agent-server/app/agent.py)
    │       └── 5 tools        (agent-server/app/tools.py)
    │               ├── list_datasets
    │               ├── get_dataset_schema
    │               ├── execute_sql
    │               ├── execute_query_plan
    │               └── execute_python
    ├── Executor factory       (agent-server/app/executors/factory.py)
    │       ├── DockerExecutor       – default, local dev
    │       ├── MicroSandboxExecutor – optional alternative
    │       └── K8sJobExecutor       – production (WIP validation)
    ├── SQL policy validator   (agent-server/app/validators/sql_policy.py)
    ├── QueryPlan compiler     (agent-server/app/validators/compiler.py)
    ├── Storage (SQLite)       (agent-server/app/storage/)
    │       ├── capsules.py    – run audit trail
    │       └── messages.py    – thread conversation history
    └── Observability
            ├── Prometheus metrics  (GET /metrics)
            └── MLflow tracing      (optional, OpenAI autolog)
    │
    ▼
Runner (container or sandbox)
    ├── runner.py              – DuckDB SQL execution
    └── runner_python.py       – Python/pandas execution (AST-validated)
    │
    ▼
CSV Datasets (mounted read-only at /data)
    ├── ecommerce/  (orders, order_items, inventory)
    ├── support/    (tickets)
    └── sensors/    (sensors)
```

### Query modes

| Mode | Trigger | Runner entrypoint |
|---|---|---|
| SQL | Default. LLM calls `execute_sql` | `runner.py` |
| QueryPlan | LLM calls `execute_query_plan` → compiled to SQL | `runner.py` |
| Python | User says "PYTHON: …" or LLM calls `execute_python` | `runner_python.py` (separate `--entrypoint`) |

### Chat fast-path

Messages prefixed with `SQL:` or `PYTHON:` bypass the LLM entirely. `_execute_direct()` in `main.py` handles these synchronously — useful for debugging and deterministic testing.

---

## File Map

```
agent-server/
├── app/
│   ├── main.py              – FastAPI app factory, Settings, all routes (1,379 lines)
│   ├── agent.py             – LangGraph agent, AgentSession, capsule extraction (528 lines)
│   ├── tools.py             – 5 LangChain tool definitions, closed over executor (232 lines)
│   ├── llm.py               – LLM factory: OpenAI / Anthropic (44 lines)
│   ├── datasets.py          – registry loader + dataset-by-id helper (23 lines)
│   ├── executors/
│   │   ├── base.py          – Executor ABC (submit_run, get_status, get_result, cleanup)
│   │   ├── factory.py       – create_sandbox_executor() — reads SANDBOX_PROVIDER
│   │   ├── docker_executor.py      – subprocess `docker run` with hardened flags
│   │   ├── microsandbox_executor.py – JSON-RPC to msb server
│   │   └── k8s_executor.py         – Kubernetes Job creation + polling
│   ├── validators/
│   │   ├── sql_policy.py    – SELECT/WITH allowlist, blocklist, token boundary check
│   │   └── compiler.py      – QueryPlan (Pydantic) → deterministic SQL
│   ├── models/
│   │   └── query_plan.py    – Pydantic models: QueryPlan, Filter, Aggregation, etc.
│   └── storage/
│       ├── capsules.py      – SQLite run_capsules table (CRUD)
│       └── messages.py      – SQLite thread_messages table + MessageStore ABC
├── Dockerfile               – local image
├── Dockerfile.k8s           – K8s image (datasets baked in)
└── requirements.txt

runner/
├── runner.py                – SQL runner: stdin JSON → DuckDB → stdout JSON
├── runner_python.py         – Python runner: AST-validated pandas execution
├── common.py                – Shared: RunnerResponse, sanitize_data_path, sanitize_table_name
├── Dockerfile               – hardened base (non-root, read-only root FS)
└── Dockerfile.k8s           – variant with datasets baked in

datasets/
├── ecommerce/               – orders.csv, order_items.csv, inventory.csv
├── support/                 – tickets.csv
├── sensors/                 – sensors.csv
└── registry.json            – full metadata catalog (schemas, prompts, version hashes)

tests/
├── unit/                    – 16 test files (compiler, query_plan, sql_policy, capsules,
│                              dataset_loader, runner, docker_executor, k8s_executor,
│                              microsandbox_executor, executor_factory, agent, tools,
│                              llm, message_store, mlflow_tracing, stack_validation,
│                              sandbox_provider_selection)
├── integration/             – 4 files (agent_server, docker_executor, microsandbox, runner)
└── security/                – 1 file (policy_security)

scripts/                     – deterministic dataset generators (seeded)
helm/csv-analyst-chat/       – K8s Helm chart (11 templates) — WIP, separate thread
docs/                        – PRDs, specs, decisions, use-cases
ui/                          – Dockerfile stub (static UI is served from agent-server)
```

---

## Configuration

All config is via environment variables, read in `create_app()` in `main.py`. A `.env` file at the repo root is auto-loaded.

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto` tries OpenAI first, then Anthropic |
| `OPENAI_API_KEY` | — | Recommended for dev |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `ANTHROPIC_API_KEY` | — | Fallback |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20240620` | |
| `SANDBOX_PROVIDER` | `docker` | `docker` \| `microsandbox` \| `k8s` |
| `RUNNER_IMAGE` | `csv-analyst-runner:test` | Must be built first (`make build-runner`) |
| `DATASETS_DIR` | `datasets` | Path to the datasets/ directory |
| `RUN_TIMEOUT_SECONDS` | `10` | Per-run hard timeout |
| `MAX_ROWS` | `200` | Result cap |
| `ENABLE_PYTHON_EXECUTION` | `true` | Feature flag for Python mode |
| `CAPSULE_DB_PATH` | `agent-server/capsules.db` | SQLite file for runs + messages |
| `STORAGE_PROVIDER` | `sqlite` | Only sqlite implemented |
| `THREAD_HISTORY_WINDOW` | `12` | Messages of context fed to LLM |
| `MLFLOW_TRACKING_URI` | — | If set, enables MLflow tracing |
| `MLFLOW_OPENAI_AUTOLOG` | `false` | Enables `mlflow.openai.autolog()` |
| `LOG_LEVEL` | `info` | |

K8s and MicroSandbox vars exist but are only active when their respective `SANDBOX_PROVIDER` value is selected. See `.env.example` for the full list.

---

## API Endpoints

All served by the single FastAPI app (`main.py`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Static chat UI (HTML) |
| GET | `/healthz` | Liveness probe |
| GET | `/metrics` | Prometheus scrape endpoint |
| GET | `/datasets` | List datasets with prompts |
| GET | `/datasets/{id}/schema` | Schema + 3 sample rows |
| POST | `/chat` | Blocking: message → agent → result |
| POST | `/chat/stream` | SSE streaming version of /chat |
| POST | `/runs` | Direct run submission (bypasses agent) |
| GET | `/runs/{run_id}` | Fetch a run capsule |
| GET | `/runs/{run_id}/status` | Run status only |
| GET | `/threads/{thread_id}/messages` | Thread conversation history |

### ChatRequest / ChatResponse

```python
# Request (POST /chat or /chat/stream)
{"dataset_id": "ecommerce", "message": "...", "thread_id": "optional", "user_id": "optional"}

# Response
{"assistant_message": "...", "run_id": "...", "thread_id": "...",
 "status": "succeeded|failed|rejected|timed_out",
 "result": {"columns": [...], "rows": [...], "row_count": N, "exec_time_ms": N, "error": ...},
 "details": {"dataset_id": "...", "query_mode": "sql|python|plan|chat", "compiled_sql": "...", ...}}
```

---

## How to Run & Test

```bash
# --- Development ---
make run-agent-dev          # Start server (uvicorn, hot-reload, uses repo .env)

# --- Testing (MUST use the agent-server venv) ---
agent-server/.venv/bin/pytest tests/unit/ -q              # All unit tests
agent-server/.venv/bin/pytest tests/unit/test_compiler.py # Specific file
agent-server/.venv/bin/pytest tests/unit/ -k "sql_policy" # By keyword

# --- Docker ---
make build-runner           # Build runner image (required before first run)
make build-agent            # Build agent-server image

# --- Datasets ---
python3 scripts/generate_ecommerce_dataset.py   # Seed 42
python3 scripts/generate_support_dataset.py     # Seed 43
python3 scripts/generate_sensors_dataset.py     # Seed 44
python3 scripts/generate_registry.py            # Regenerate registry.json
python3 scripts/validate_datasets.py            # Validate integrity
```

---

## Key Code Patterns

### App factory and dependency injection

`create_app(settings, llm, executor)` accepts optional overrides for all three dependencies. Tests inject mocks this way — no patching needed.

```python
# In tests:
app = create_app(settings=test_settings, llm=mock_llm, executor=mock_executor)
```

### Executor interface

All backends implement `Executor` (base.py):
- `submit_run(payload, query_type)` → `{"run_id", "status", "result"}`
- `get_status(run_id)` → `{"run_id", "status"}`
- `get_result(run_id)` → result dict or None
- `cleanup(run_id)` → void

`DockerExecutor` runs `docker run` via subprocess with hardened flags (`--network none`, `--read-only`, `--pids-limit 64`, `--memory 512m`, `--cpus 0.5`).

### Runner stdin/stdout contract

```json
// stdin (RunnerRequest)
{"dataset_id": "ecommerce", "files": [{"name": "orders", "path": "/data/ecommerce/orders.csv"}],
 "query_type": "sql", "sql": "SELECT ...", "timeout_seconds": 10, "max_rows": 200, "max_output_bytes": 65536}

// stdout (RunnerResponse)
{"status": "success", "columns": [...], "rows": [...], "row_count": N, "exec_time_ms": N}
```

For Python mode, replace `"sql"` with `"python_code"` and set `"query_type": "python"`.

### SQL policy

`validate_sql_policy()` enforces:
- Must start with `SELECT` or `WITH`
- No semicolons (single statement only)
- Token-boundary blocklist: `drop`, `delete`, `insert`, `update`, `create`, `alter`, `attach`, `install`, `load`, `pragma`, `call`, `copy`, `export`
- Boundary check prevents false positives (`created_at` does not match `create`)

`normalize_sql_for_dataset()` strips dataset-qualified table references (`ecommerce.orders` → `orders`) before validation and execution.

### QueryPlan DSL

Pydantic models in `models/query_plan.py`. Compiled to SQL by `validators/compiler.py`. Supports:
- Filters: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `between`, `contains`, `startswith`, `endswith`, `is_null`, `is_not_null`
- Aggregations: `count`, `count_distinct`, `sum`, `avg`, `min`, `max`
- `group_by`, `order_by`, `limit` (defaults to 200 if omitted)

### Python execution safety

`runner_python.py` does AST validation before execution:
- Blocks: `open`, `exec`, `eval`, `__import__`, subprocess/network/filesystem modules
- Allows: `pandas`, `numpy`, basic builtins
- Result must be set via `result_df`, `result_rows`, or `result`

### Capsule persistence

Every execution (whether via agent or direct run) produces a capsule stored in SQLite (`run_capsules` table). Fields include: `run_id`, `dataset_id`, `question`, `query_mode`, `plan_json`, `compiled_sql`, `python_code`, `status`, `result_json`, `error_json`, `exec_time_ms`.

### Thread-based conversation

Messages are persisted per `thread_id` in `thread_messages`. The last `THREAD_HISTORY_WINDOW` messages are converted to LangChain message objects and passed as history context to the agent on each turn.

---

## What's Implemented vs Planned

### Implemented (don't rebuild these)
- Dataset generation, registry, validation
- QueryPlan DSL + SQL compiler + tests
- SQL policy validator
- DuckDB SQL runner + Docker container
- Python/pandas runner with AST safety policy
- DockerExecutor (default sandbox backend)
- MicroSandboxExecutor (alternative backend, JSON-RPC)
- K8sJobExecutor (backend implementation done; live cluster validation pending)
- LangGraph react agent with 5 tools
- Stateful multi-turn conversations (thread_id + message history)
- Run capsule storage and retrieval
- Static chat UI served from FastAPI
- FastAPI endpoints (chat, stream, runs, datasets, threads)
- Prometheus metrics (`/metrics`)
- MLflow tracing (optional, OpenAI autolog)
- Structured JSON logging with request-id correlation
- CI/CD (GitHub Actions: lint, test, build, push to GHCR)

### In progress / pending
- K8s live-cluster acceptance testing (Helm chart exists; kind smoke test needs validation)
- Phase 2 security hardening checklist (runner security context verification in K8s)
- Phase 3 documentation polish (quickstart guides, hosting runbook)
- Phase 3 acceptance testing (12+ curated prompts end-to-end)
- Phase 4 stretch goals (query caching, chart output, multi-turn derived tables)

---

## Security Model

- **SQL**: Allowlist (SELECT/WITH only) + token blocklist with boundary matching
- **Sandbox**: `--network none`, `--read-only`, `--pids-limit 64`, `--memory 512m`, `--cpus 0.5`, `--tmpfs /tmp`
- **Python**: AST-level import/call blocklist before execution
- **Output**: Max 200 rows, 64KB stdout/stderr
- **Data exfil heuristic**: Compiler rejects queries selecting many columns without aggregation or limit
- **K8s**: NetworkPolicy denies egress, Pod Security Standards, drop ALL capabilities

---

## Common Pitfalls

1. **venv**: Tests fail with system Python. Always use `agent-server/.venv/bin/pytest`.
2. **Runner image**: Must run `make build-runner` before the server can execute queries.
3. **Dataset paths**: Runner sees datasets at `/data/...` (mounted volume). Agent-server sees them at `datasets/...` (relative to CWD). `registry.json` `files[].path` is the relative path; executor prepends `/data/`.
4. **SQL normalization**: `ecommerce.orders` in LLM-generated SQL must be stripped to `orders` before reaching the runner. `normalize_sql_for_dataset()` does this.
5. **LLM provider**: If neither `OPENAI_API_KEY` nor `ANTHROPIC_API_KEY` is set, `create_llm()` raises. Tests should inject a mock LLM via `create_app(llm=...)`.
6. **Capsule DB**: Both capsules and thread messages share the same SQLite file (default: `agent-server/capsules.db`).
7. **Python execution**: Controlled by `ENABLE_PYTHON_EXECUTION`. When false, `execute_python` returns a `FEATURE_DISABLED` error.

---

## References

- `.env.example` — full config reference with comments
- `docs/DECISIONS.md` — architecture decision log
- `docs/features/` — feature specs (MicroSandbox, Python execution, K8s deployment, etc.)
- `docs/PRD/` — product requirements
- `TODO.md` — phased task list with status
- `CHANGELOG.md` — version history
- `Makefile` — run `make help` for all targets

---

*Last updated: 2026-02-03*
