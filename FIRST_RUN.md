# FIRST RUN (Local, Docker Sandbox)

This is the **exact** sequence for a fresh clone to run the project locally.

## Minimum Requirements

- `git`
- `make`
- `python3` (tested with Python 3.13)
- `docker` (daemon running) **required for sandboxed query execution**
- `curl`
- OpenAI API key (`OPENAI_API_KEY`)

Notes:
- Kubernetes, Helm, and MicroSandbox are **not** required for first local run.
- Node/npm are **not** required (UI is served by FastAPI from `agent-server/app/main.py`).

## 1) Clone and enter repo

```bash
git clone <YOUR_REPO_URL>
cd adoptaisandbox
```

## 2) Preflight checks

```bash
python3 --version
docker --version
docker info --format '{{.ServerVersion}}'
make --version
curl --version
```

If `docker info` fails, start Docker first.

## 3) Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=<YOUR_KEY>
SANDBOX_PROVIDER=docker
RUNNER_IMAGE=csv-analyst-runner:test
MLFLOW_ENABLED=false
```

## 4) Create Python virtualenv + install deps

```bash
make agent-venv
```

## 5) Build the local runner image (Docker sandbox)

```bash
make build-runner-test
```

Optional quick check:

```bash
docker run --rm --entrypoint python3 csv-analyst-runner:test -c "print('runner_ok')"
```

## 6) Start the server

```bash
make run-agent-dev
```

Expected startup line includes:
- `Uvicorn running on http://0.0.0.0:8000`

## 7) Verify from a second terminal

Health:

```bash
curl -sS http://127.0.0.1:8000/healthz
```

Datasets:

```bash
curl -sS http://127.0.0.1:8000/datasets
```

Force an actual sandboxed SQL run:

```bash
curl -sS -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  --data-binary '{"dataset_id":"support","thread_id":"first-run","message":"SQL: SELECT COUNT(*) AS n FROM tickets"}'
```

Expected:
- response `status` is `succeeded`
- `result.rows` is non-empty

## 8) Open UI

- Open `http://127.0.0.1:8000`

## Optional one-command validation

After setup, you can run:

```bash
OPENAI_API_KEY=<YOUR_KEY> make first-run-check
```

This performs a deterministic pass/fail startup + sandbox query verification.

## Common Failures

- `No LLM key configured...`
  - `.env` missing/invalid `OPENAI_API_KEY`.
- `Error response from daemon ... image ... not found`
  - run `make build-runner-test`.
- MLflow connection warnings
  - keep `MLFLOW_ENABLED=false` for local first run.
