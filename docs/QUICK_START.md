# Quick Start Guide

Get the current PoC running locally (single-file FastAPI server + sandboxed runner).

## Prerequisites

- Python 3.11+ preferred
- Docker
- Make

## 1) Install agent-server dependencies

```bash
make agent-venv
```

This creates/updates `agent-server/.venv` and is the environment used by `make run-agent*` and test targets.

## 2) Configure environment

Copy root env template and set your provider key:

```bash
cp .env.example .env
```

`.env` must live at:
- `/home/juancho/projects/adoptaisandbox/.env`

Set at least one key:

```bash
OPENAI_API_KEY=...
# and/or
ANTHROPIC_API_KEY=...
```

Optional provider selection:

```bash
LLM_PROVIDER=auto  # auto|openai|anthropic
ENABLE_PYTHON_EXECUTION=true
SANDBOX_PROVIDER=docker  # docker|microsandbox
MSB_SERVER_URL=http://127.0.0.1:5555/api/v1/rpc
MSB_API_KEY=
MSB_NAMESPACE=default
MSB_MEMORY_MB=512
MSB_CPUS=1.0
STORAGE_PROVIDER=sqlite
THREAD_HISTORY_WINDOW=12
```

## 3) Build runner image used by tests/server

```bash
make build-runner-test
```

## 4) Run tests (sanity)

```bash
agent-server/.venv/bin/pytest tests/unit/test_query_plan.py tests/unit/test_compiler.py -q
make test-agent-server
make test-runner
make test-microsandbox

# Run live MicroSandbox integration tests (requires reachable MicroSandbox server)
RUN_MICROSANDBOX_TESTS=1 make test-microsandbox
```

## 5) Start server + UI

```bash
make run-agent-dev
```

Open:
- `http://localhost:8000`

Use the UI to select dataset and send a question, or explicit execution mode:
- `SQL: SELECT ...`
- `PYTHON: result_df = tickets.groupby('priority').size().reset_index(name='n')`

## Useful Commands

```bash
make run-agent
make run-agent-dev
make run-agent-microsandbox
make test-agent-server
make test-runner
make test-microsandbox
make test-unit
```

## Notes

- QueryPlan DSL is handled in agent-server (`demo_query_plan.py` + compiler).
- Runner executes SQL and restricted Python (separate entrypoints in the same image); it does not parse QueryPlan JSON.
- Streaming endpoint is `POST /chat/stream` and the static UI consumes it.
