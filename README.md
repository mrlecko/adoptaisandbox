# CSV Analyst Chat

LLM-assisted CSV analysis with sandboxed SQL execution.

## Current Status (2026-02-03)

Implemented now:
- ✅ Dataset generation + registry (`datasets/registry.json`)
- ✅ QueryPlan DSL + deterministic compiler (`agent-server/demo_query_plan.py` flow)
- ✅ Hardened runner container for SQL + restricted Python execution (`runner/runner.py`, `runner/runner_python.py`)
- ✅ Single-file FastAPI agent server (`agent-server/app/main.py`)
- ✅ Minimal static UI served by the same FastAPI app (`GET /`)
- ✅ Streaming chat endpoint (`POST /chat/stream`) and run capsule persistence (`SQLite`)
- ✅ Integration tests for runner + single-file server
- ✅ Makefile now enforces `agent-server/.venv` for server/test commands
- ✅ LLM structured-output hardening (dict output coercion + SQL rescue pass)
- ✅ SQL policy hardening (word-boundary denylist + dataset-qualified table normalization)
- ✅ Python sandbox execution mode in same runner image via separate entrypoint (`runner/runner_python.py`)

In progress:
- 🚧 Stronger SQL policy coverage and red-team scenarios
- 🚧 Richer LLM planning behavior and recovery loops
- 🚧 K8s/Helm production path

## Architecture (Current)

1. UI (static page from FastAPI) calls `/chat` or `/chat/stream`.
2. Agent server generates/accepts query intent (plan or SQL).
3. QueryPlan (if used) is compiled to SQL in agent-server.
4. SQL/Python execution happens only inside the configured sandbox provider (`docker` or `microsandbox`).
5. Result + metadata are stored in run capsules and returned to the UI.

Important arrangement:
- The runner does **not** parse QueryPlan DSL.
- QueryPlan DSL remains upstream in agent-server (`agent-server/demo_query_plan.py`, compiler, validators).
- Runner receives SQL/Python payload + dataset file mapping only.

## Quick Start

### 1) Install dependencies

```bash
make agent-venv
```

### 2) Configure environment

Create `.env` at the **repository root** (`/home/juancho/projects/adoptaisandbox/.env`):

```bash
cp .env.example .env
```

Set at least one provider key:

```bash
# choose one
OPENAI_API_KEY=...
# or
ANTHROPIC_API_KEY=...
```

### 3) Build runner test image

```bash
make build-runner-test
```

### 4) Run the server

```bash
make run-agent-dev
# or: make run-agent
```

Then open `http://localhost:8000`.

## API Surface (Single-File Server)

- `GET /healthz`
- `GET /datasets`
- `GET /datasets/{dataset_id}/schema`
- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/status`
- `POST /chat`
- `POST /chat/stream` (SSE)
- `GET /threads/{thread_id}/messages`
- `GET /` (minimal static UI)

Message modes:
- Natural language (default planning path)
- `SQL: ...` for explicit SQL execution
- `PYTHON: ...` for explicit Python sandbox execution (feature-flagged by `ENABLE_PYTHON_EXECUTION`)
- Stateful conversations via `thread_id` (UI persists thread IDs in browser local storage)

## Testing

```bash
# QueryPlan + compiler unit tests
pytest tests/unit/test_query_plan.py tests/unit/test_compiler.py -q

# Single-file server integration tests
make test-agent-server

# Runner + DockerExecutor integration tests
make test-runner
```

Current validated counts:
- `104` unit tests
- `25` single-file server integration tests
- `14` runner + DockerExecutor integration tests
- `4` MicroSandbox integration tests (opt-in; run with `RUN_MICROSANDBOX_TESTS=1`)
- `6` security policy tests
- `153` tests total (`135` pass + `18` environment-dependent skips under plain `make test`)

## Make Targets You’ll Use Most

- `make run-agent`
- `make run-agent-dev`
- `make run-agent-microsandbox`
- `make test-agent-server`
- `make test-runner`
- `make test-microsandbox`
- `make test-unit`

## MicroSandbox Troubleshooting

- If MicroSandbox tests are skipped, set `RUN_MICROSANDBOX_TESTS=1`.
- If provider startup fails, verify `MSB_SERVER_URL` and that `/api/v1/health` is reachable.
- Ensure `RUNNER_IMAGE` is available to the MicroSandbox runtime.
- Use `SANDBOX_PROVIDER=docker` as the default fallback during local development.

## Key Environment Variables

Defined in `.env.example`:
- `LLM_PROVIDER` (`auto|openai|anthropic`)
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `DATASETS_DIR`, `CAPSULE_DB_PATH`
- `RUNNER_IMAGE`, `RUN_TIMEOUT_SECONDS`, `MAX_ROWS`, `LOG_LEVEL`
- `SANDBOX_PROVIDER` (`docker|microsandbox`)
- `MSB_SERVER_URL`, `MSB_API_KEY`, `MSB_NAMESPACE`, `MSB_MEMORY_MB`, `MSB_CPUS`
- `MAX_OUTPUT_BYTES`, `ENABLE_PYTHON_EXECUTION`
- `STORAGE_PROVIDER` (`sqlite` currently)
- `THREAD_HISTORY_WINDOW` (messages sent to LLM per thread)

## Project Structure

```text
.
├── agent-server/
│   ├── app/
│   │   ├── main.py               # single-file FastAPI server
│   │   ├── models/query_plan.py  # QueryPlan DSL
│   │   └── validators/compiler.py
│   └── demo_query_plan.py
├── datasets/
├── runner/
├── tests/
├── docs/
└── Makefile
```

## Notes

- This repo is optimized for a clear PoC narrative: deterministic DSL + secure execution boundary + minimal server/UI footprint.
- For the detailed server design, see `AGENT_SERVER_SPECIFICATION.md`.
- For the Python-in-runner extension plan (same image, separate entrypoint), see `PYTHON_EXECUTION_SPEC.md`.
