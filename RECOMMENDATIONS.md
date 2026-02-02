# CSV Analyst Chat - Repository Review & Recommendations

Date: 2026-02-02

## Executive Verdict

The project documentation is strong and interview-grade, but the repository is currently a scaffold, not a runnable PoC.  

- **Sufficient to start building?** Yes (good structure and clear specs).
- **Sufficient to run/test locally or in a prod-like environment today?** No (critical implementation files are missing).

## What Is Strong

- Clear product direction and requirements in `docs/PRD/Core PRD.md` and `docs/PRD/Deployment PRD.md`.
- Good phased execution strategy in `docs/IMPLEMENTATION_PLAN.md`.
- Intended architecture is practical for interview evaluation (agent + sandbox + deployability).
- Existing top-level structure (`agent-server`, `runner`, `ui`, `helm`, `tests`, `datasets`) is the right shape.

## Critical Gaps (Blockers)

1. **Core implementation files are missing**
   - `agent-server` only has `README.md` (no app code, Dockerfile, dependencies).
   - `runner` only has `README.md` (no `runner.py`, no Dockerfile).
   - `ui` is empty.
   - `helm` is empty.

2. **Datasets are not present**
   - `datasets/registry.json` missing.
   - No CSV datasets/directories for ecommerce, support, sensors.

3. **Local execution path is not runnable**
   - `docker-compose.yml` references missing Dockerfiles/services.
   - `make smoke` and `make k8s-smoke` are TODO placeholders in `Makefile`.

4. **CI is configured against files that do not exist**
   - `.github/workflows/ci.yml` expects `agent-server/requirements.txt`, code for linting, and executable tests.

5. **Documentation/status drift**
   - `README.md` marks MVP items complete that are not implemented yet.
   - `README.md` links to missing docs (`docs/hosting.md`, `docs/troubleshooting.md`).
   - `CLAUDE.md` references PRD paths that do not exist (`docs/PRD/core_prd.md`, `docs/PRD/deployment_prd.md`).

## Recommendations (Priority Order)

### P0 - Make the repo truthful and bootstrappable (immediate)

- Align docs to current reality (mark as scaffold/in-progress).
- Add missing minimum files so commands do not fail:
  - `agent-server/Dockerfile`, `agent-server/requirements.txt`, minimal FastAPI app (`/healthz`).
  - `runner/Dockerfile`, `runner/runner.py` with JSON in/out contract.
  - `ui` starter app with Dockerfile.
- Update `Makefile` targets so `make dev`, `make smoke`, and `make clean` are real.

### P1 - Deliver a true local vertical slice (must-have for interview)

- Implement dataset registry + 3 datasets with prompts in `datasets/`.
- Implement JSON QueryPlan schema + compiler + SQL validator.
- Implement Docker executor with required sandbox flags.
- Wire `POST /chat` end-to-end: question -> plan/SQL -> sandbox execution -> table output.
- Persist run capsules (SQLite) and expose `GET /runs/{run_id}`.

### P2 - Prove prod-like path (second differentiator)

- Implement Helm chart in `helm/csv-analyst-chat/` with:
  - UI + agent Deployments/Services/Ingress
  - RBAC scoped to Jobs/Pods/logs
  - execution mode + resource limits in values
- Add K8s Job executor and `make k8s-smoke`.
- Add one documented hosting runbook + fallback runbook.

### P3 - Interview polish (top-tier signal)

- Add real test coverage in `tests/unit`, `tests/integration`, `tests/security`.
- Ensure one-command verification:
  - local: `make dev && make smoke`
  - k8s: `make k8s-up && make helm-install && make k8s-smoke`
- Add a short "security proof" section in README:
  - sandbox flags
  - denylist/validation behavior
  - red-team test results

## Suggested Readiness Gates

- **Gate 1 (Local MVP):** `docker compose up` works, 3 canonical prompts succeed, run capsules retrievable.
- **Gate 2 (Prod-like):** Helm deploy works on kind/k3d, each query spawns runner Job, result returns to UI.
- **Gate 3 (Interview-ready):** docs match reality, smoke tests are deterministic, CI green.

## Final Assessment

This is a **high-potential scaffold** with excellent planning artifacts. To be competitive for an interview demo, prioritize converting plan/docs into a thin but real end-to-end implementation before adding advanced features.
