# Kubernetes + Helm Deployment Specification

**Date:** 2026-02-03  
**Status:** Increment 2 implemented (native `K8sJobExecutor` + chart/schema updates); live-cluster acceptance pending

---

## 1) Exact Helm Chart Structure

```text
helm/csv-analyst-chat/
├── Chart.yaml
├── values.yaml
├── values.schema.json
└── templates/
    ├── _helpers.tpl
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── serviceaccount.yaml
    ├── secret-env.yaml
    ├── role.yaml
    ├── rolebinding.yaml
    ├── pvc.yaml
    ├── networkpolicy.yaml
    └── NOTES.txt
```

Current deployment shape:
- Deploys **one FastAPI service** (agent server + static UI served at `/`).
- Supports persistent storage for capsules (`/app/capsules`).
- Supports secret-based API key injection.
- Pre-provisions RBAC hooks for future in-cluster job execution.

---

## 2) Values Schema (Implemented)

`values.schema.json` validates these major groups:
- `image.*`, `replicaCount`, `resources`
- `service.*`, `ingress.*`
- `serviceAccount.*`, `rbac.*`
- `persistence.*`
- `datasets.*` (optional PVC mount for dataset files)
- `env.*` (runtime configuration passed to app)
- `existingSecretName` / `secretEnv.*`
- `networkPolicy.*`

Notable enums:
- `env.LLM_PROVIDER`: `auto|openai|anthropic`
- `env.SANDBOX_PROVIDER`: `docker|microsandbox|k8s`

---

## 3) Local Deployment Test Path (Easiest)

### Prereqs
- Docker
- kind
- kubectl
- helm

### Commands

```bash
# 1) Create local cluster
make k8s-up

# 2) Build an agent image with datasets baked in
make build-agent-k8s K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev

# 3) Load image into kind
make kind-load-agent-image K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev

# 4) Render/lint chart (optional)
make helm-template K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev

# 5) Install chart
make helm-install K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev

# 6) Smoke test
make k8s-smoke
```

### Important local note
For native in-cluster runner Jobs, set:
- `env.SANDBOX_PROVIDER=k8s`
- `env.RUNNER_IMAGE=<runner image with datasets baked into /data>`

---

## 4) Remote Deployment Options

### Option A (Recommended for interview): **Managed Kubernetes** (DigitalOcean Kubernetes / DOKS)

Why it is easiest for interview signaling:
- Faster path to public HTTPS URL.
- Less cluster-ops overhead than self-managed control plane.
- Cleaner “production-minded” story (RBAC, ingress, Helm release management).

High-level flow:
1. Create a small DOKS cluster (2 nodes is enough for demo).
2. Install ingress-nginx.
3. Push image(s) to GHCR.
4. `helm upgrade --install ...` with image repo/tag + env vars.
5. Point DNS to LoadBalancer and validate `/healthz`, `/metrics`, query flow.

### Option B: **Small VPS (DigitalOcean Droplet) + k3s**

Pros:
- Lowest cost, full control.

Cons:
- More ops burden (TLS, ingress, upgrades, backups, node reliability).
- Weaker interview signal vs managed K8s for “production-ready Kubernetes”.

**Recommendation:** use DOKS unless cost constraints force single-node k3s.

---

## 5) Current Gaps to Close (Next Increment)

1. Validate `K8sJobExecutor` end-to-end on kind and one remote cluster (DOKS/k3s).
2. Wire runner pod NetworkPolicy guarantees for in-cluster Job pods (deny egress by default, allow only explicit exceptions).
3. Upgrade `k8s-smoke` to run a deterministic `/chat` query and verify capsule/result state.
4. Add CI checks for Helm lint/template and optional kind smoke profile.

---

## 6) Operational Runbook

For executable local + remote procedures (including dependency lists, end-to-end `/runs` checks, and troubleshooting), use:

- `docs/runbooks/K8S_HELM_DOCKER_RUNBOOK.md`
- `docs/runbooks/K8S_HELM_PROFILE_CONTEXTS.md` (separate Helm profile contexts for `k8s` and `microsandbox`)
