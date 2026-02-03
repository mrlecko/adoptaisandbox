# Kubernetes + Helm Runbook (Docker-Image Sandbox, No MicroSandbox)

This runbook documents how to deploy and operate the project on Kubernetes with Helm while using **containerized runner execution** (the `k8s` sandbox provider), not MicroSandbox.

If you need side-by-side profile contexts (`k8s` and `microsandbox`), see:
- `docs/runbooks/K8S_HELM_PROFILE_CONTEXTS.md`

## 0) Scope and Mode

- Use: `SANDBOX_PROVIDER=k8s`
- Do **not** use: `SANDBOX_PROVIDER=microsandbox`
- Runner isolation is still container-based (Docker image), but orchestration/execution is done by Kubernetes Jobs.

---

## 1) Local Environment Runbook (kind)

Quick path (if `OPENAI_API_KEY` is already exported):

```bash
make deploy-all-local
```

### 1.1 Dependencies (human + agent)

Required:
- Docker Engine (daemon running)
- `kind`
- `kubectl`
- `helm` (>=3)
- `make`
- `curl`

Recommended:
- `jq`
- `python3`

Repo/runtime:
- `agent-server/.venv` dependencies installed (`make agent-venv`)
- `.env` in repo root with `OPENAI_API_KEY` (or Anthropic equivalent)

### 1.2 Known-good local deployment sequence

From repo root:

```bash
# 1) Python env for tests/tools
make agent-venv

# 2) Build local images
make build-runner-k8s K8S_IMAGE_TAG=dev
make build-agent-k8s K8S_IMAGE_REPOSITORY=csv-analyst-agent K8S_IMAGE_TAG=dev

# 3) Create cluster
make k8s-up

# 4) Load both images into kind
kind load docker-image csv-analyst-runner:dev --name csv-analyst
kind load docker-image csv-analyst-agent:dev --name csv-analyst

# 5) Ensure kubectl context is set
kubectl config use-context kind-csv-analyst
kubectl get nodes

# 6) Create API key secret (replace with your key)
kubectl -n csv-analyst create namespace csv-analyst --dry-run=client -o yaml | kubectl apply -f -
kubectl -n csv-analyst create secret generic csv-analyst-llm \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# 7) Install/upgrade Helm release
helm upgrade --install csv-analyst ./helm/csv-analyst-chat -n csv-analyst \
  --set image.repository=csv-analyst-agent \
  --set image.tag=dev \
  --set image.pullPolicy=Never \
  --set existingSecretName=csv-analyst-llm \
  --set env.LLM_PROVIDER=openai \
  --set env.SANDBOX_PROVIDER=k8s \
  --set env.RUNNER_IMAGE=csv-analyst-runner:dev \
  --set env.K8S_NAMESPACE=csv-analyst

# 8) Wait for app rollout
kubectl -n csv-analyst rollout status deploy/csv-analyst-csv-analyst-chat --timeout=240s

# 9) Baseline smoke
make k8s-smoke
```

### 1.3 Functional verification (`/runs`)

```bash
kubectl -n csv-analyst port-forward svc/csv-analyst-csv-analyst-chat 18000:8000
```

In a second terminal:

```bash
curl -sS -X POST http://127.0.0.1:18000/runs \
  -H "Content-Type: application/json" \
  --data-binary '{
    "dataset_id":"support",
    "query_type":"sql",
    "sql":"SELECT COUNT(*) AS ticket_count FROM tickets"
  }'
```

Expected:
- `"status":"succeeded"`
- non-empty `rows`

---

## 2) Remote VPS Runbook (Single-node k3s)

This is the fastest non-managed remote path that still demonstrates Kubernetes + Helm + Job execution.

### 2.1 Dependencies

On VPS (Ubuntu 22.04+):
- `k3s`
- `kubectl` (bundled with k3s symlink)

On workstation:
- `docker` (for image build/push)
- `kubectl`
- `helm`
- SSH access to VPS

### 2.2 Build and publish images

Use GHCR (or another registry):

```bash
docker login ghcr.io

# Agent image
docker build -f agent-server/Dockerfile.k8s -t ghcr.io/<user>/adoptaisandbox-agent-server:<tag> .
docker push ghcr.io/<user>/adoptaisandbox-agent-server:<tag>

# Runner image
docker build -f runner/Dockerfile.k8s -t ghcr.io/<user>/adoptaisandbox-runner:<tag> .
docker push ghcr.io/<user>/adoptaisandbox-runner:<tag>
```

### 2.3 Install k3s on VPS

```bash
curl -sfL https://get.k3s.io | sh -
sudo kubectl get nodes
```

Copy kubeconfig locally:

```bash
scp <vps>:/etc/rancher/k3s/k3s.yaml ~/.kube/config-csv-analyst
# Update server address in file from 127.0.0.1 to VPS public IP/DNS
export KUBECONFIG=~/.kube/config-csv-analyst
kubectl get nodes
```

### 2.4 Deploy via Helm

```bash
kubectl create namespace csv-analyst --dry-run=client -o yaml | kubectl apply -f -

# LLM key secret
kubectl -n csv-analyst create secret generic csv-analyst-llm \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# Optional: image pull secret if repo is private
kubectl -n csv-analyst create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<user> \
  --docker-password=<token> \
  --docker-email=<email> \
  --dry-run=client -o yaml | kubectl apply -f -
```

Deploy:

```bash
helm upgrade --install csv-analyst ./helm/csv-analyst-chat -n csv-analyst \
  --set image.repository=ghcr.io/<user>/adoptaisandbox-agent-server \
  --set image.tag=<tag> \
  --set image.pullPolicy=Always \
  --set existingSecretName=csv-analyst-llm \
  --set env.LLM_PROVIDER=openai \
  --set env.SANDBOX_PROVIDER=k8s \
  --set env.RUNNER_IMAGE=ghcr.io/<user>/adoptaisandbox-runner:<tag> \
  --set env.K8S_NAMESPACE=csv-analyst
```

Validate:

```bash
kubectl -n csv-analyst rollout status deploy/csv-analyst-csv-analyst-chat --timeout=300s
kubectl -n csv-analyst get pods
```

Expose app quickly (port-forward):

```bash
kubectl -n csv-analyst port-forward svc/csv-analyst-csv-analyst-chat 8000:8000
```

Then run the same `/runs` verification query as local.

---

## 3) Agent-Oriented Operational Checklist

Use this strict checklist for deterministic automation:

1. `kubectl config current-context` is non-empty and points to intended cluster.
2. `kubectl get nodes` succeeds.
3. `helm lint ./helm/csv-analyst-chat` passes.
4. Release values enforce:
   - `env.SANDBOX_PROVIDER=k8s`
   - `env.RUNNER_IMAGE=<valid image>`
   - `env.K8S_NAMESPACE=<namespace>`
5. Rollout complete:
   - `kubectl -n <ns> rollout status deploy/csv-analyst-csv-analyst-chat`
6. Health passes:
   - `GET /healthz` returns 200.
7. Functional run passes:
   - `POST /runs` SQL returns `status=succeeded`.
8. Runner job observed:
   - `kubectl -n <ns> get jobs` shows a completed job for the run.

---

## 4) Troubleshooting (from real local bring-up)

### `kubectl ... localhost:8080 connect refused`
- Cause: no kube context selected.
- Fix: set context (`kubectl config use-context kind-csv-analyst`).

### `ImagePullBackOff` for `csv-analyst-agent:dev`
- Cause: local image not present in kind node.
- Fix: `kind load docker-image ...` and set `image.pullPolicy=Never`.

### `/healthz` returns 500 in pod
- Common cause: missing API key secret / LLM init failure.
- Fix: create secret and set `existingSecretName` + `env.LLM_PROVIDER`.

### `jobs ... forbidden ... jobs/status`
- Cause: RBAC missing `jobs/status`.
- Fix: upgrade chart version/templates with `jobs/status` permission.

### `runAsNonRoot ... non-numeric user (runner)`
- Cause: runner pod security requires explicit numeric UID/GID.
- Fix: set `run_as_user=1000`, `run_as_group=1000` in K8s executor container security context.

### `Runner returned invalid JSON` from `/runs`
- Known parser edge case fixed in latest executor:
  - supports JSON and Python-literal dict log output.
- Ensure latest agent image is loaded and rollout completed.

### `kind load docker-image ... no space left on device`
- Cause: disk/tmp exhaustion.
- Fix: free disk space, rerun image load/redeploy.

---

## 5) Cleanup

Local:

```bash
helm uninstall csv-analyst -n csv-analyst
make k8s-down
```

Remote:

```bash
helm uninstall csv-analyst -n csv-analyst
kubectl delete ns csv-analyst
# Optional: uninstall k3s on VPS
sudo /usr/local/bin/k3s-uninstall.sh
```
