# Solution Architecture Map and Discussion

This is a human-readable map of the full solution, aligned with `project.canvas`.

---

## 1) High-Level Map (Layered View)

1. **Goal + Use Cases**
   - Natural-language analytics over fixed CSV datasets.
   - Use cases: ecommerce, support tickets, sensors.

2. **Interaction Layer**
   - Static chat UI served by FastAPI (`GET /`).
   - Calls `/chat` or `/chat/stream` and shows result/details panels.

3. **API + Orchestration Layer**
   - `agent-server/app/main.py` routes and app wiring.
   - `agent-server/app/agent.py` LangChain/LangGraph tool-calling session loop.
   - `agent-server/app/tools.py` execution and metadata tools.

4. **Validation + Query Construction**
   - QueryPlan DSL (`agent-server/demo_query_plan.py`).
   - Compiler + SQL policy validators (`agent-server/app/validators/*`).

5. **Sandbox Execution Layer**
   - Provider abstraction (`agent-server/app/executors/*`), selected by `SANDBOX_PROVIDER`.
   - Backends: `docker`, `k8s`, `microsandbox`.
   - Runner image (`runner/`) executes SQL or Python via separate entrypoints.

6. **Data + State Layer**
   - Built-in datasets under `datasets/` + `datasets/registry.json`.
   - Message history and run capsules in SQLite via storage abstraction.

7. **Operability Layer**
   - `/healthz`, `/metrics`, structured logs, request IDs.
   - Optional MLflow tracing (gated behind `MLFLOW_ENABLED`).

8. **Deployment Layer**
   - Local Docker path.
   - Kubernetes/Helm path with native K8s Job execution.
   - Kubernetes profile for MicroSandbox-based execution.

---

## 2) End-to-End Request Logic

1. User chooses a dataset and asks a question.
2. API receives request (`/chat` or `/chat/stream`) and resolves thread context.
3. Agent graph decides which tool(s) to call:
   - dataset/schema lookup tools for context,
   - execution tools for SQL/Python when data computation is required.
4. Execution tools validate/normalize requests (QueryPlan compile + SQL policy checks).
5. Executor dispatches request to sandbox backend.
6. Runner executes against dataset CSVs and returns bounded JSON result.
7. API persists capsule + message history and returns:
   - assistant message,
   - run status,
   - result payload/details.

Key design rule: **no direct execution in agent process**; only sandbox paths execute code/query.

---

## 3) Use Case Features and Decision Logic

## Supported interaction modes
- **Natural language (default):** agent plans and decides tool usage.
- **Explicit SQL (`SQL: ...`):** executes validated SQL directly.
- **Explicit Python (`PYTHON: ...`):** executes restricted Python in sandbox (feature-flagged).

## Conversational behavior
- Stateful by `thread_id`.
- Prior successful runs in-thread can inform follow-up refinement.
- Non-data conversational prompts can be answered without forced execution.

## Result behavior
- Structured result includes columns/rows/row_count/exec_time/error metadata.
- UI keeps detailed result panel separate from assistant narrative.

---

## 4) Sandbox Options (Execution Context)

## A) Docker (default local)
- Best for local development and deterministic debugging.
- Requires local Docker daemon and runner image build.

## B) Kubernetes Job (`SANDBOX_PROVIDER=k8s`)
- Agent creates per-run Jobs, reads logs/results, and returns output.
- Best for production-like isolation and deployment narrative.

## C) MicroSandbox (`SANDBOX_PROVIDER=microsandbox`)
- External sandbox service profile.
- Useful alternative runtime story; needs reachable service/auth configuration.

---

## 5) Deployment Map (Local and Remote)

## Local developer flow
- Setup venv and dependencies.
- Build runner image.
- Run FastAPI server.
- Query via UI/API with Docker sandbox.

## Local K8s validation flow
- Build agent/runner k8s images.
- Load into kind.
- Helm install profile.
- Run smoke + functional `/runs` checks.

## Remote flow (VPS/managed K8s)
- Push images to registry.
- Provision cluster + secrets.
- Helm install/upgrade with selected sandbox provider.
- Verify rollout, health, and functional runs.

---

## 6) Make Utility Map (Operational Use)

## Bootstrap and run
- `make agent-venv`
- `make build-runner-test`
- `make run-agent-dev`

## Test and quality
- `make test-agent-server`
- `make test-runner`
- `make test-security`
- `make lint`

## K8s and Helm
- `make k8s-deploy-k8s-job`
- `make helm-install-k8s-job`
- `make helm-install-microsandbox`
- `make k8s-smoke`
- `make k8s-test-runs`

## One-command convenience
- `make deploy-all-local` (local setup + kind deploy + functional run check)

---

## 7) What to Edit for Specific Changes

- API contracts/route behavior: `agent-server/app/main.py`
- Agent reasoning/tool loop: `agent-server/app/agent.py`
- Tool I/O and execution calls: `agent-server/app/tools.py`
- SQL/DSL validation behavior: `agent-server/app/validators/*`
- Sandbox backend behavior: `agent-server/app/executors/*`
- SQL/Python runtime semantics: `runner/*.py`
- K8s deployment semantics: `helm/csv-analyst-chat/*`

---

## 8) Architecture Strengths, Limits, and Next Hardening Steps

## Strengths
- True tool-calling agent architecture with isolated execution.
- Multi-provider sandbox abstraction.
- Stateful conversation + auditable run capsules.
- Strong local + k8s deployment story.

## Limits
- Some CI/deployment edges still depend on strict environment consistency.
- Validation is policy-focused; stricter AST-level SQL checks remain an upgrade path.
- Performance/concurrency evidence is not yet fully formalized.

## Next hardening steps
1. Enforce a single deterministic golden-path smoke command in CI.
2. Add explicit performance baseline and concurrency test artifacts.
3. Tighten SQL validation depth and publish threat model notes.
4. Keep docs/TODO status synchronized after each architectural patch.

