# AGENT_SIGNPOST.md

Agent orientation guide for this repository.  
Audience: new LLM/code agents joining mid-stream.

---

## 1) Mission and Success Criteria

This project is a **sandboxed CSV analytics agent**:
- User asks natural language questions about built-in CSV datasets.
- Agent plans and executes SQL/Python **only via sandbox executors**.
- Results are returned with traceable run metadata (capsules/history).

If you are making changes, your default success criteria are:
1. No regression to local Docker sandbox flow.
2. `make run-agent-dev` remains usable.
3. Existing tests continue to pass (or new failures are understood and documented).
4. Docs and Make usage stay accurate.

Shared alignment references:
- Operating philosophy: `MANIFESTO.md`
- Status source of truth: `TODO.md`
- Verification evidence: `docs/EVIDENCE.md`

---

## 2) Fast Project Mental Model

Request path:
1. UI (`GET /`) sends `/chat` or `/chat/stream`.
2. Agent graph (LangChain/LangGraph) chooses tools.
3. Tool calls execute SQL/Python in configured sandbox (`docker|k8s|microsandbox`).
4. Runner returns bounded JSON result.
5. Server persists capsule/message history and responds to UI.

Critical rule: **the model does not execute code directly**; execution goes through executor tools.

---

## 3) Repo Footprint (Where to Go)

## Core runtime
- `agent-server/app/main.py`  
  FastAPI app wiring, env/settings, routes, middleware, metrics, startup.
- `agent-server/app/agent.py`  
  LangGraph agent build/session loop, capsule extraction, history behavior.
- `agent-server/app/tools.py`  
  Agent tools and tool I/O contracts.
- `agent-server/app/executors/`  
  Sandbox backends:
  - `docker_executor.py`
  - `k8s_executor.py`
  - `microsandbox_executor.py`
  - `factory.py` selection logic
- `runner/runner.py` + `runner/runner_python.py` + `runner/common.py`  
  Sandboxed SQL/Python execution internals.

## Data + schemas
- `datasets/` and `datasets/registry.json`  
  Built-in datasets and metadata.
- `agent-server/demo_query_plan.py` and `agent-server/app/validators/`  
  QueryPlan DSL + compiler/policy logic.

## Persistence
- `agent-server/app/storage/`  
  Capsules + message history (SQLite abstraction).

## Deploy
- `helm/csv-analyst-chat/`  
  K8s manifests/templates/values/profiles.
- `docs/runbooks/`  
  Operational deployment flows.

## Tests
- `tests/unit/`
- `tests/integration/`
- `tests/security/`

---

## 4) Makefile Utilities (Practical Guide)

The Makefile is broad; some targets are mature and some are placeholders.

## A. Daily working targets (reliable)
- `make agent-venv`  
  Create/update `agent-server/.venv` and install dependencies.
- `make build-runner-test`  
  Build local runner image (`csv-analyst-runner:test`) for Docker sandbox tests and dev.
- `make run-agent-dev`  
  Start FastAPI with reload on `0.0.0.0:8000`.
- `make run-agent`  
  Start FastAPI without reload.
- `make test-agent-server`  
  Integration tests for server behavior.
- `make test-runner`  
  Runner + Docker executor integration tests.
- `make test-unit` / `make test-security` / `make test-integration` / `make test`
- `make lint` / `make format`

## B. Local first-run path
- Use `FIRST_RUN.md` for exact bootstrap sequence.
- Minimum local requirement for sandbox execution: **Docker daemon running**.

## C. Kubernetes path (mature)
- `make k8s-up`
- `make build-agent-k8s`
- `make build-runner-k8s`
- `make k8s-load-images`
- `make helm-install[-k8s-job|-microsandbox]`
- `make k8s-smoke`
- `make k8s-test-runs`

## D. Convenience deploy bundles
- `make local-deploy`
- `make deploy-all-local` (full local + kind + functional `/runs` check)
- `make k8s-deploy-k8s-job`
- `make k8s-deploy-microsandbox`

## E. Targets with TODO stubs (do not assume production-ready)
- `make push`
- `make release`
- `make db-migrate`
- `make db-reset`
- `make docs-serve`
- `make docs-build`
- `make smoke` (currently placeholder)

If you touch these, either implement fully or keep docs explicit about their status.

---

## 5) Environment Expectations

`.env` should live at repo root.  
Minimum variables for local OpenAI + Docker flow:
- `LLM_PROVIDER=openai`
- `OPENAI_API_KEY=...`
- `SANDBOX_PROVIDER=docker`
- `RUNNER_IMAGE=csv-analyst-runner:test`
- `MLFLOW_ENABLED=false` (default-safe; enable only when tracing intentionally)

Important:
- MLflow tracing is gated. If disabled, server should not depend on local MLflow server.
- Missing runner image leads to execution failures; build it with `make build-runner-test`.

---

## 6) Change Routing: “If you need to modify X, start here”

- Conversation behavior/tool choice:
  - `agent-server/app/agent.py`
  - `agent-server/app/tools.py`
- API shape/response payload/UI data contract:
  - `agent-server/app/main.py`
  - relevant integration tests in `tests/integration/test_agent_server_singlefile.py`
- SQL safety/normalization:
  - `agent-server/app/validators/sql_policy.py`
- QueryPlan DSL/compiler behavior:
  - `agent-server/demo_query_plan.py`
  - `agent-server/app/validators/compiler.py`
- Runner execution semantics/timeouts/output limits:
  - `runner/common.py`
  - `runner/runner.py`
  - `runner/runner_python.py`
- Sandbox backend-specific failures:
  - corresponding executor under `agent-server/app/executors/`
- K8s behavior:
  - `helm/csv-analyst-chat/*`
  - `agent-server/app/executors/k8s_executor.py`

---

## 7) Testing Strategy for Agents (Speed vs Confidence)

Use this sequence:
1. **Targeted unit tests** for touched modules.
2. **Relevant integration test file(s)**.
3. `make lint`.
4. Broader suite only when needed (`make test` can be slow).

Suggested quick checks:
- Server contract/regression: `make test-agent-server`
- Runner regression: `make test-runner`
- Security policy path: `make test-security`

If a test is slow/hanging:
- Run single test with `-k` first.
- Verify env/sandbox prerequisites (`RUNNER_IMAGE`, Docker daemon, provider settings).

---

## 8) Known Sharp Edges

- Port 8000 conflicts can look like startup failures.
- Docker image tag mismatches (`RUNNER_IMAGE`) are a common source of false failures.
- K8s local flow requires correct context and loaded local images in kind.
- Some workflow/docs items may lag implementation; keep docs synchronized when you patch.
- Long integration runs can mask simple setup issues; prefer tactical tests first.

---

## 9) Agent Working Agreement (Recommended)

When implementing:
1. State assumptions (provider, env, dataset, target test scope).
2. Make smallest safe patch set first.
3. Validate with targeted tests.
4. Update docs/changelog if behavior or workflow changed.
5. Report what you validated vs what remains unverified.

This repository is evaluated partly on engineering discipline, not just feature count.

---

## 10) First References to Open

For fastest onboarding, read in this order:
1. `README.md`
2. `FIRST_RUN.md`
3. `agent-server/app/main.py`
4. `agent-server/app/agent.py`
5. `agent-server/app/tools.py`
6. `runner/runner.py` and `runner/runner_python.py`
7. `tests/integration/test_agent_server_singlefile.py`
8. `DEPLOYMENT.md`
