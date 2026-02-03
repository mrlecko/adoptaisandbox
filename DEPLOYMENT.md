# DEPLOYMENT GUIDE

This guide explains the **WHAT**, **WHY**, and **HOW** for deploying this project across local and Kubernetes environments.

---

## WHAT (Solution Overview)

This project is a CSV-analysis agent stack:

1. **Agent Server** (`agent-server/app/main.py`)
   - FastAPI app with chat + tool-calling orchestration.
   - Serves static UI and APIs (`/chat`, `/runs`, `/datasets`, `/healthz`).

2. **Runner Image** (`runner/`)
   - Sandboxed execution runtime for SQL/Python over CSV datasets.

3. **Helm Chart** (`helm/csv-analyst-chat`)
   - Deploys the agent server on Kubernetes.
   - Supports multiple sandbox execution providers:
     - `k8s` (native K8s Job executor)
     - `microsandbox` (external MicroSandbox service)
     - `docker` (local/non-K8s baseline)

---

## WHY (Deployment Options and Tradeoffs)

### Option A: Local FastAPI + Docker runner
- **Use when:** fast local iteration, debugging code/tests.
- **Why:** simplest loop, lowest operational overhead.

### Option B: Kubernetes + native K8s Job executor (`SANDBOX_PROVIDER=k8s`)
- **Use when:** demonstrating production-like architecture on Kubernetes.
- **Why:** sandbox runs as per-query Kubernetes Jobs, RBAC-controlled.

### Option C: Kubernetes + MicroSandbox (`SANDBOX_PROVIDER=microsandbox`)
- **Use when:** you need MicroSandbox specifically and have reachable MSB server.
- **Why:** separates sandbox runtime concerns from the cluster.

Recommendation for interview/demo:
- Use **Option B** for the primary story.
- Keep **Option C** as an alternate profile.

---

## HOW (Idiot-Proof Commands)

## 0) Fastest end-to-end command

If you want one command that does local setup + kind deployment + functional `/runs` verification:

```bash
export OPENAI_API_KEY=...
make deploy-all-local
```

## 1) Local deployment (non-K8s)

### Prerequisites
- `python3`
- `docker`
- `make`

### Commands

```bash
# One-time setup
make local-deploy

# Start server (in this shell)
make run-agent-dev

# In another shell, smoke-check
make local-smoke
```

Notes:
- Put your key in env or `.env`:
  - `export OPENAI_API_KEY=...`
  - or copy `.env.example` to `.env` and set values.

---

## 2) Local Kubernetes (kind) with native Job sandbox (recommended)

### Prerequisites
- `docker`
- `kind`
- `kubectl`
- `helm`
- `make`
- `curl`
- `OPENAI_API_KEY` exported in shell

### One-command deployment

```bash
export OPENAI_API_KEY=...
make k8s-deploy-k8s-job
```

What this does:
- checks prereqs
- creates kind cluster
- builds agent + runner images
- loads images into kind
- creates LLM secret
- installs Helm with `SANDBOX_PROVIDER=k8s`
- runs smoke checks

### Functional run check

```bash
make k8s-test-runs
```

Expected:
- `/runs` returns `status: succeeded` with non-empty rows.

---

## 3) Kubernetes with MicroSandbox (separate context/profile)

### Prerequisites
- same as K8s mode, plus a reachable MicroSandbox server URL.

### One-command deployment

```bash
export OPENAI_API_KEY=...
make k8s-deploy-microsandbox MSB_SERVER_URL=http://<msb-host>:5555/api/v1/rpc
```

### Functional note
- `make k8s-smoke` validates service readiness only.
- `/runs` will succeed **only** if `MSB_SERVER_URL` is reachable from cluster pods.

---

## 4) Remote VPS (k3s) deployment

Use the runbook:
- `docs/runbooks/K8S_HELM_DOCKER_RUNBOOK.md`

For profile context details (`k8s` vs `microsandbox`):
- `docs/runbooks/K8S_HELM_PROFILE_CONTEXTS.md`

---

## 5) Helm profile shortcuts

```bash
make helm-template-k8s-job
make helm-template-microsandbox
make helm-install-k8s-job
make helm-install-microsandbox
```

---

## 6) Troubleshooting fast path

- No kube context / `localhost:8080` errors:
  - `kubectl config use-context kind-csv-analyst`
- Image pull errors in kind:
  - ensure `kind load docker-image ...` was run
  - use `image.pullPolicy=Never` in local kind
- Pod health failures:
  - `kubectl -n csv-analyst logs deploy/csv-analyst-csv-analyst-chat`
- Functional run failures:
  - `make k8s-test-runs`
  - inspect runner jobs: `kubectl -n csv-analyst get jobs,pods`
