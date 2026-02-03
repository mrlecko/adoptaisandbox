# CSV Analyst Chat

LLM-assisted CSV analysis with sandboxed SQL/Python execution.

## Current Status (2026-02-03)

Implemented now:
- ✅ Dataset generation + registry (`datasets/registry.json`)
- ✅ QueryPlan DSL + deterministic compiler (`agent-server/demo_query_plan.py` flow)
- ✅ Hardened runner container for SQL + restricted Python execution (`runner/runner.py`, `runner/runner_python.py`)
- ✅ FastAPI agent server with LangChain/LangGraph tool-calling agent flow (`agent-server/app/main.py`, `agent-server/app/agent.py`, `agent-server/app/tools.py`)
- ✅ Minimal static UI served by the same FastAPI app (`GET /`)
- ✅ Streaming chat endpoint (`POST /chat/stream`) and run capsule persistence (`SQLite`)
- ✅ Integration tests for runner + single-file server
- ✅ Makefile now enforces `agent-server/.venv` for server/test commands
- ✅ LLM structured-output hardening (dict output coercion + SQL rescue pass)
- ✅ SQL policy hardening (word-boundary denylist + dataset-qualified table normalization)
- ✅ Python sandbox execution mode in same runner image via separate entrypoint (`runner/runner_python.py`)

In progress:
- 🚧 Kubernetes/Helm production hardening and live-cluster validation
- 🚧 Final security hardening/documentation for production profile

## Architecture (Current)

1. UI (static page from FastAPI) calls `/chat` or `/chat/stream`.
2. LangChain/LangGraph agent decides tool calls (dataset/schema lookup, SQL/Python execution).
3. QueryPlan (if used) is compiled to SQL in agent-server.
4. SQL/Python execution happens only inside the configured sandbox provider (`docker`, `microsandbox`, or `k8s`).
5. Result + metadata are stored in run capsules and returned to the UI.

Important arrangement:
- The runner does **not** parse QueryPlan DSL.
- QueryPlan DSL remains upstream in agent-server (`agent-server/demo_query_plan.py`, compiler, validators).
- Runner receives SQL/Python payload + dataset file mapping only.

## Quick Start

For a strict, copy/paste first-run guide, see `FIRST_RUN.md`.

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

Optional (observability with MLflow tracing):

```bash
make run-mlflow
```

Use the Make target (instead of invoking `mlflow` directly) so the venv bin
path is injected; this ensures MLflow can find `huey_consumer.py`.

Then set in `.env` (repo root), and restart the agent server:

```bash
MLFLOW_ENABLED=true
MLFLOW_OPENAI_AUTOLOG=true
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_EXPERIMENT_NAME=CSV Analyst Agent
```

MLflow notes:
- Open `http://localhost:5000` and inspect traces under the `CSV Analyst Agent` experiment.
- `/chat` and `/chat/stream` are traced with per-turn metadata:
  - `mlflow.trace.user` (from `user_id`)
  - `mlflow.trace.session` (from `thread_id`)
- The static UI auto-persists:
  - `thread_id` in `localStorage.csvAnalystThreadId`
  - `user_id` in `localStorage.csvAnalystUserId`
- Trace input now includes the chat payload (`dataset_id`, `message`, `thread_id`, `input_mode`) so prompts are visible in MLflow.

## API Surface (Single-File Server)

- `GET /healthz`
- `GET /metrics` (Prometheus text format)
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
- Optional per-user trace metadata via `user_id` + `thread_id` on `/chat` and `/chat/stream` when MLflow tracking is enabled
  - Static UI auto-generates a stable `user_id` in browser local storage (`csvAnalystUserId`)

## Testing

```bash
# QueryPlan + compiler unit tests
pytest tests/unit/test_query_plan.py tests/unit/test_compiler.py -q

# Single-file server integration tests
make test-agent-server

# Runner + DockerExecutor integration tests
make test-runner
```

Current suite:
- Unit tests (`tests/unit`)
- Integration tests (`tests/integration`)
- Security tests (`tests/security`)
- Optional live MicroSandbox integration (`RUN_MICROSANDBOX_TESTS=1`)

Tip:
- `agent-server/.venv/bin/pytest tests --collect-only -q` shows the current collected test total for your local branch.

## Make Targets You’ll Use Most

- `make run-agent`
- `make run-agent-dev`
- `make run-agent-microsandbox`
- `make run-mlflow`
- `make test-agent-server`
- `make test-runner`
- `make test-microsandbox`
- `make test-unit`

Deployment convenience targets:
- `make local-deploy` (checks prerequisites + local setup)
- `make deploy-all-local` (one command: local setup + kind deploy + functional `/runs` check)
- `make k8s-deploy-k8s-job` (one-command kind deploy, native K8s Job sandbox)
- `make k8s-deploy-microsandbox MSB_SERVER_URL=...` (one-command kind deploy, MicroSandbox profile)
- `make k8s-test-runs` (functional `/runs` SQL check)

## Kubernetes + Helm (Increment 2)

Helm chart location:
- `helm/csv-analyst-chat`

Core deployment commands:

```bash
make k8s-up
make build-agent-k8s K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev
make build-runner-k8s K8S_IMAGE_TAG=dev
make kind-load-agent-image K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev
make helm-install K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev K8S_SANDBOX_PROVIDER=k8s
make k8s-smoke
```

Fastest end-to-end local path (requires `OPENAI_API_KEY`):

```bash
export OPENAI_API_KEY=...
make deploy-all-local
```

Profile shortcuts:

```bash
make helm-template-k8s-job
make helm-template-microsandbox
make helm-install-k8s-job
make helm-install-microsandbox
```

For in-cluster runner jobs, set:
- `SANDBOX_PROVIDER=k8s`
- `RUNNER_IMAGE=<runner image with datasets at /data>` (for local kind, use `make build-runner-k8s`)

Detailed deployment spec and remote-hosting guidance:
- `docs/features/HELM_K8S_DEPLOYMENT_SPEC.md`
- `docs/runbooks/K8S_HELM_DOCKER_RUNBOOK.md` (local kind + remote VPS runbook, `SANDBOX_PROVIDER=k8s`, no MicroSandbox)
- `docs/runbooks/K8S_HELM_PROFILE_CONTEXTS.md` (separate Helm profile contexts for `k8s` vs `microsandbox`)
- `DEPLOYMENT.md` (WHAT/WHY/HOW deployment guide with one-command local + K8s flows)

## MicroSandbox Troubleshooting

- If MicroSandbox tests are skipped, set `RUN_MICROSANDBOX_TESTS=1`.
- If provider startup fails, verify `MSB_SERVER_URL` and that `/api/v1/health` is reachable.
- If `RUNNER_IMAGE` is not pullable by MicroSandbox, the executor falls back to `msb exe` using `MSB_FALLBACK_IMAGE` and mounted runner files.
- Use `SANDBOX_PROVIDER=docker` as the default fallback during local development.

## Key Environment Variables

Defined in `.env.example`:
- `LLM_PROVIDER` (`auto|openai|anthropic`)
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `DATASETS_DIR`, `CAPSULE_DB_PATH`
- `RUNNER_IMAGE`, `RUN_TIMEOUT_SECONDS`, `MAX_ROWS`, `LOG_LEVEL`
- `SANDBOX_PROVIDER` (`docker|microsandbox|k8s`)
- `K8S_NAMESPACE`, `K8S_SERVICE_ACCOUNT_NAME`, `K8S_IMAGE_PULL_POLICY`
- `K8S_CPU_LIMIT`, `K8S_MEMORY_LIMIT`, `K8S_DATASETS_PVC`
- `K8S_JOB_TTL_SECONDS`, `K8S_POLL_INTERVAL_SECONDS`
- `MSB_SERVER_URL`, `MSB_API_KEY`, `MSB_NAMESPACE`, `MSB_MEMORY_MB`, `MSB_CPUS`
- `MSB_CLI_PATH`, `MSB_FALLBACK_IMAGE` (optional MicroSandbox CLI fallback controls)
- `MAX_OUTPUT_BYTES`, `ENABLE_PYTHON_EXECUTION`
- `STORAGE_PROVIDER` (`sqlite` currently)
- `THREAD_HISTORY_WINDOW` (messages sent to LLM per thread)
- `MLFLOW_OPENAI_AUTOLOG`, `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME` (optional OpenAI autolog tracing)
- `MLFLOW_ENABLED` (master on/off switch for all MLflow tracing)

## Telemetry Quickstart

- Request correlation:
  - Every response includes `x-request-id` (server-generated when missing).
  - Structured logs include `request_id`; chat/run logs also include thread/run identifiers.
- Metrics endpoint:
  - `GET /metrics` exposes Prometheus counters/histograms.
  - Key metrics:
    - `csv_analyst_http_requests_total`
    - `csv_analyst_http_request_duration_seconds`
    - `csv_analyst_agent_turns_total`
    - `csv_analyst_sandbox_runs_total`

## Project Structure

```text
.
├── agent-server/
│   ├── app/
│   │   ├── main.py               # FastAPI routes + wiring
│   │   ├── agent.py              # LangGraph/LangChain agent loop
│   │   ├── tools.py              # Agent tools (execute SQL/Python, schema lookup, etc.)
│   │   ├── llm.py                # LLM/provider factory
│   │   ├── models/query_plan.py  # QueryPlan DSL
│   │   ├── executors/            # Docker, MicroSandbox, and K8s Job executors
│   │   └── validators/compiler.py
│   └── demo_query_plan.py
├── datasets/
├── runner/
├── tests/
├── docs/
└── Makefile
```

## Notes

- This repo is optimized for a clear PoC narrative: deterministic DSL + secure execution boundary + pragmatic tool-calling agent.
- For the detailed server design, see `AGENT_SERVER_SPECIFICATION.md`.
- For the Python-in-runner extension plan (same image, separate entrypoint), see `PYTHON_EXECUTION_SPEC.md`.
