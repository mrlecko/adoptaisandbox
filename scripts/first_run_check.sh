#!/usr/bin/env bash
set -euo pipefail

PORT="${FIRST_RUN_PORT:-18080}"
HOST="${FIRST_RUN_HOST:-127.0.0.1}"
BASE_URL="http://${HOST}:${PORT}"
LOG_DIR="${FIRST_RUN_LOG_DIR:-./docs/evidence/logs}"
LOG_FILE="${LOG_DIR}/first_run_check.log"

mkdir -p "${LOG_DIR}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: $1"
    exit 1
  fi
}

require_cmd python3
require_cmd docker
require_cmd curl

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not reachable. Start Docker and try again."
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: No LLM key configured."
  echo "Set OPENAI_API_KEY or ANTHROPIC_API_KEY and rerun."
  exit 1
fi

if [[ -n "${LLM_PROVIDER:-}" ]]; then
  EFFECTIVE_PROVIDER="${LLM_PROVIDER}"
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  EFFECTIVE_PROVIDER="openai"
else
  EFFECTIVE_PROVIDER="anthropic"
fi

if [[ ! -x "agent-server/.venv/bin/python" ]]; then
  echo "ERROR: agent virtualenv missing. Run: make agent-venv"
  exit 1
fi

echo "[1/6] Verifying runner image..."
if ! docker image inspect "${RUNNER_IMAGE:-csv-analyst-runner:test}" >/dev/null 2>&1; then
  echo "Runner image missing. Building csv-analyst-runner:test..."
  make build-runner-test >/dev/null
fi

echo "[2/6] Starting agent server on ${BASE_URL}..."
env \
  OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  LLM_PROVIDER="${EFFECTIVE_PROVIDER}" \
  SANDBOX_PROVIDER="${SANDBOX_PROVIDER:-docker}" \
  RUNNER_IMAGE="${RUNNER_IMAGE:-csv-analyst-runner:test}" \
  MLFLOW_ENABLED="${MLFLOW_ENABLED:-false}" \
  agent-server/.venv/bin/uvicorn app.main:app \
    --app-dir agent-server \
    --host "${HOST}" \
    --port "${PORT}" \
    >"${LOG_FILE}" 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "${SERVER_PID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[3/6] Waiting for /healthz..."
READY=0
for _ in $(seq 1 90); do
  if curl -sf "${BASE_URL}/healthz" >/tmp/csv_analyst_healthz.json 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done

if [[ "${READY}" -ne 1 ]]; then
  echo "ERROR: Server failed to become healthy."
  echo "--- server log tail ---"
  tail -n 120 "${LOG_FILE}" || true
  exit 1
fi

echo "[4/6] Checking dataset registry endpoint..."
curl -sf "${BASE_URL}/datasets" >/tmp/csv_analyst_datasets.json

echo "[5/6] Running deterministic SQL execution check via /chat..."
curl -sf -X POST "${BASE_URL}/chat" \
  -H "Content-Type: application/json" \
  --data-binary '{"dataset_id":"support","thread_id":"first-run-check","message":"SQL: SELECT COUNT(*) AS n FROM tickets"}' \
  >/tmp/csv_analyst_chat_sql.json

echo "[6/6] Validating response contracts..."
python3 <<'PY'
import json

with open("/tmp/csv_analyst_healthz.json", "r", encoding="utf-8") as f:
    health = json.load(f)
with open("/tmp/csv_analyst_datasets.json", "r", encoding="utf-8") as f:
    datasets = json.load(f)
with open("/tmp/csv_analyst_chat_sql.json", "r", encoding="utf-8") as f:
    chat = json.load(f)

assert health.get("status") == "ok", health
ids = {d.get("id") for d in datasets.get("datasets", [])}
assert {"ecommerce", "support", "sensors"}.issubset(ids), ids
assert chat.get("status") == "succeeded", chat
result = chat.get("result", {})
assert result.get("row_count") == 1, result
rows = result.get("rows") or []
assert rows and isinstance(rows[0][0], int), rows
print("PASS: first-run-check contract assertions succeeded.")
PY

echo "PASS: first-run-check completed."
echo "Log file: ${LOG_FILE}"
