# PRD Addendum: Local Dev, Environments, Deployment Plan, Hosting Action Item

## A) Environments & Goals

### ENV-1: Local developer environment (mandatory)

**Goal:** Anyone can run the full system on a laptop in ≤10 minutes with one command.

**Requirements**

- Must run end-to-end locally: UI → agent server → sandbox runner → results.
    
- Must not require Kubernetes locally.
    
- Must have deterministic datasets locally.
    
- Must have a smoke test command that verifies the full happy path.
    

**Acceptance criteria**

- `docker compose up` brings up UI + agent server, and runner execution works via Docker sandbox mode.
    
- A scripted smoke test (e.g. `make smoke`) executes at least 3 canonical prompts (one per dataset) and returns a non-empty table result.
    
- Clear error messages when Docker isn’t installed / daemon not running.
    

### ENV-2: Local Kubernetes (staging-like) (recommended)

**Goal:** Verify the Kubernetes Job runner mode and Helm chart without needing a cloud account.

**Requirements**

- Must support `kind` or `k3d` cluster.
    
- Must install via Helm.
    
- Must run at least one query end-to-end using K8s Jobs.
    

**Acceptance criteria**

- `make k8s-up` (kind/k3d) + `helm install ...` results in a working UI + agent server.
    
- Running a query triggers a Kubernetes Job for the runner and returns results.
    

### ENV-3: Online deployment (mandatory)

**Goal:** Publicly accessible URL for evaluation. Must use Helm and Kubernetes Job sandboxing.

**Requirements**

- Helm chart supports configurable ingress host + TLS configuration.
    
- Images are built and published to a container registry.
    
- The agent server has namespace-scoped RBAC to create Jobs + read Pods/logs.
    

**Acceptance criteria**

- Fresh cluster deploy in ≤20 minutes from README steps.
    
- Public URL loads UI, chat works, runner Jobs execute, results show.
    

---

## B) Local Runtime Specification (Docker Compose)

### Required services (compose)

1. **UI**
    
2. **Agent server**
    
3. _(No always-on runner service)_ — runner executes as ephemeral Docker containers created by agent server
    

### Local mode execution mechanics

**Requirement:** agent server must support **DockerExecutor** mode:

- Uses Docker Engine to run `runner:latest` with:
    
    - `--network none`
        
    - `--read-only`
        
    - `--pids-limit 64`
        
    - `--memory 512m --cpus 0.5`
        
    - `--tmpfs /tmp:rw,noexec,nosuid,size=64m`
        
    - mount datasets read-only at `/data`
        
- Runner reads request JSON and prints result JSON to stdout.
    

### Local developer commands (must exist)

- `make dev` → starts compose, builds images if needed
    
- `make smoke` → runs 3 demo prompts end-to-end and asserts results
    
- `make clean` → stops and removes containers
    

### Local config (env vars)

- `EXECUTION_MODE=docker`
    
- `MAX_ROWS=200`
    
- `RUN_TIMEOUT_MS=5000`
    
- `DATASETS_PATH=/data`
    

---

## C) Kubernetes Runtime Specification (Helm + Jobs)

### Kubernetes mode execution mechanics

**Requirement:** agent server must support **K8sJobExecutor** mode:

- Creates a Job per query with:
    
    - Runner image
        
    - Input payload via env var or mounted config (preferred: small JSON via env)
        
    - Dataset access (MVP: baked into image OR mounted read-only volume)
        
    - Security context:
        
        - `runAsNonRoot: true`
            
        - `allowPrivilegeEscalation: false`
            
        - `readOnlyRootFilesystem: true`
            
        - `capabilities: drop: ["ALL"]`
            
    - Resource limits:
        
        - cpu/mem configurable via Helm values
            
    - **NetworkPolicy**: default deny egress for runner pods
        

### Helm chart must include

- Deployments: UI + agent server
    
- Service + Ingress for UI and agent server (or UI only if UI proxies)
    
- RBAC:
    
    - ServiceAccount for agent server
        
    - Role/RoleBinding restricted to:
        
        - Jobs: create/get/list/watch
            
        - Pods: get/list/watch (for job pods)
            
        - Pod logs: get (depending on cluster)
            
- Values for:
    
    - image tags
        
    - ingress host
        
    - TLS on/off
        
    - execution mode (k8s)
        
    - runner limits, timeout, max rows
        

### Kubernetes developer commands (must exist)

- `make k8s-up` → creates kind/k3d cluster
    
- `make helm-install` → installs chart into namespace
    
- `make helm-uninstall`
    
- `make k8s-smoke` → triggers a run and verifies result via API
    

---

## D) Hosting Action Item (explicit requirement)

### FR-HOST-1: Provide a documented hosting plan

**Requirement:** The repo must include a “Hosting & Deployment” section that supports at least one concrete hosting target and explains tradeoffs.

**Minimum deliverable**

- One “recommended default” hosting path with exact steps.
    
- One alternative path (fallback) with steps.
    
- A decision matrix (cost/effort/security/features).
    

### Recommended default hosting path (fastest to a public URL)

**Option 1: Managed Kubernetes**

- Recommended providers (pick one):
    
    - DigitalOcean managed Kubernetes (simple UX)
        
    - Google Cloud (managed Kubernetes)
        
    - Amazon Web Services (managed Kubernetes)
        
    - Microsoft Azure (managed Kubernetes)
        

**Why:** cleanest story for evaluators: “K8s + Helm + Job sandboxing” in its native habitat.

**Deliverable:** a runbook:

- create cluster
    
- push images to registry
    
- set Helm values (image tags, ingress host)
    
- install
    
- verify with smoke test
    
- teardown steps
    

### Fallback hosting path (if you want max speed + minimal cloud complexity)

**Option 2: Single VM running k3s**

- Rent a small VM, install k3s, deploy Helm chart.
    
- Pros: very fast, cheap, single moving part.
    
- Cons: less “managed,” but still K8s + Helm + Jobs and totally valid.
    

**Deliverable:** a runbook:

- provision VM
    
- install k3s
    
- install ingress controller
    
- deploy Helm chart
    
- add TLS (Let’s Encrypt) or run HTTP-only for take-home
    

### Decision matrix (must appear in README)

|Option|Time-to-live|Complexity|Cost control|“K8s-native” story|Notes|
|---|--:|--:|--:|--:|---|
|Managed K8s|Medium|Medium|Medium|Excellent|Best evaluator optics|
|k3s on VM|Fast|Low–Medium|Good|Good|Best speed-to-demo|
|PaaS only|Fast|Low|Medium|Weak|Hard to meet “K8s Job sandbox” requirement|

**Action item outcome:** Choose one default by end of Day 1 so Day 2 is just hardening + polish.

---

## E) CI/CD & Artifact Publishing (needed for online deploy)

### FR-CICD-1: Build and publish images

**Requirement:** CI builds and pushes:

- `ui:<tag>`
    
- `agent-server:<tag>`
    
- `runner:<tag>`
    

Recommended: GitHub Actions → GHCR (simple for take-home).

### FR-CICD-2: Helm values support image tags

- `values.yaml` supports:
    
    - `image.repository`
        
    - `image.tag`
        
    - `image.pullPolicy`
        

### FR-CICD-3: One-command “release-ish” flow

- `make release TAG=...`:
    
    - builds images
        
    - pushes
        
    - prints the Helm install command for that tag
        

---

## F) README additions (must-have)

### README sections

1. **Quickstart (Local)**
    
    - prerequisites
        
    - `make dev`
        
    - open UI
        
    - run 3 canned prompts
        
2. **Quickstart (Local Kubernetes)**
    
    - `make k8s-up`
        
    - `make helm-install`
        
3. **Deploy Online**
    
    - the chosen default hosting runbook
        
4. **Security Model**
    
    - what’s sandboxed, what’s validated, what’s restricted
        
5. **Troubleshooting**
    
    - common errors: Docker daemon, image pull, RBAC, Jobs stuck, etc.
        

---

## G) Acceptance criteria updates (explicit)

Add these to “Definition of Done”:

-  Local: `docker compose up` + `make smoke` passes
    
-  Local K8s: `make k8s-up` + `make k8s-smoke` passes
    
-  Online: Helm deploy produces a public URL, and a smoke test passes
    
-  README includes a concrete hosting path and a fallback
    

---

## Recommended default choice (so you don’t stall)

If you need a “ship it” default right now: **k3s on a single VM** is usually the fastest way to get a public URL with Helm + Job sandboxing and minimal account ceremony. Managed K8s is the “best optics” option if you already have credentials handy.