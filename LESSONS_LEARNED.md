# LESSONS_LEARNED.md

What specifically went wrong during this build, what would have been better, and how to avoid repeating it.

---

## 1) Requirement and Scope Issues

## Issue: We did not freeze the primary architecture early enough
- We iterated between “single FastAPI classic flow”, “true tool-calling agent”, UI variants, and LangGraph questions.
- Result: rework in `app/main.py`, tests, and UI expectations.

## Better
- Freeze architecture at day 0:
  - single FastAPI app
  - tool-calling agent (mandatory)
  - static UI served from app
  - execution only via sandbox tools.

## Issue: “MVP” vs “stretch” boundaries were blurry in execution
- Python execution, MicroSandbox, MLflow, K8s, and UX changes overlapped before baseline stability was fully locked.
- Result: multiple regression loops.

## Better
- Hard sequence:
  1) Docker baseline + deterministic smoke
  2) tool-calling correctness
  3) tests/CI hardening
  4) optional providers/features.

---

## 2) Contract and Behavior Issues

## Issue: API/behavior contracts shifted without immediate test refactor
- Example: `run_id` behavior changed (UUID vs stub value), tests still assumed `fake-run`.
- Example: MLflow tests expected tracing from tracking URI alone after adding `MLFLOW_ENABLED` gate.

## Better
- When contracts change, update:
  - API tests
  - docs
  - changelog
  in the same patch.

## Issue: Conversational behavior had hidden policy assumptions
- “Hi” and schema prompts initially triggered unnecessary execution, then required additional control logic.

## Better
- Declare explicit intent taxonomy early:
  - conversational (no execution)
  - data question (must execute)
  - explicit SQL/Python (direct execution path).

---

## 3) Tooling and Environment Issues

## Issue: MLflow introduced startup/runtime fragility
- Tracing attempted network calls even when local MLflow server wasn’t available.
- Produced noisy retry warnings and operator confusion.

## Better
- Optional integrations must be hard-gated by default (`MLFLOW_ENABLED=false`) and fail-open.

## Issue: Virtualenv/runtime consistency drift
- Python versions and dependency behavior differed across local/CI phases.

## Better
- Pin the CI Python version to intended local baseline and validate key commands there.

## Issue: Formatting/lint scope mismatch
- CI failed `black --check` on files not consistently formatted locally.

## Better
- Define formatter scope policy explicitly:
  - either full repo always
  - or intentionally scoped and documented.

---

## 4) Integration and CI Issues

## Issue: CI pipeline order allowed late discovery of core runtime failures
- Integration problems surfaced after image build/push attempts.

## Better
- CI gates should be ordered:
  1) lint + unit/security
  2) agent integration
  3) docker runner integration
  4) image build/push.

## Issue: GHCR/org-style permission errors and registry assumptions
- Pipeline failed with package permission/push policy problems.

## Better
- Standardize registry permissions and ownership model early.
- Include a CI checklist for GHCR prerequisites.

## Issue: Runner image availability mismatch in CI tests
- Integration tests expected `csv-analyst-runner:test` but image was missing in environment.

## Better
- Build test image in the same job right before runner integration tests.

---

## 5) Kubernetes and Helm Issues

## Issue: Local k8s bring-up friction (context, image pull policy, line wrapping)
- `kubectl` context errors, `ImagePullBackOff`, broken multiline `--set` usage, rollout confusion.

## Better
- Use explicit “idiot-proof” deploy targets and preflight checks.
- Prefer profile values files over long `--set` chains for reliability.
- Include one canonical local-k8s command flow with verification and rollback steps.

## Issue: Runtime RBAC/security context gaps found late
- Needed fixes for `jobs/status` permission and numeric UID/GID security context.

## Better
- Add a static RBAC/security validation checklist before live smoke testing.

---

## 6) Test Execution and Reliability Issues

## Issue: Some test commands appeared to hang or ran much longer than expected
- Caused by environment constraints, lingering processes, and expensive suites being run too early.

## Better
- Tactical test protocol:
  - run focused test file first
  - run broad suite only after targeted pass.
- Add expected-duration notes per suite.

## Issue: Evidence claims were initially verbal, not artifact-backed
- Hard to prove status quickly during review.

## Better
- Maintain `docs/EVIDENCE.md` with command outputs and log file references.

---

## 7) Process and Communication Issues

## Issue: Multiple docs tracked status informally
- README, TODO, PRD could drift.

## Better
- Single status source of truth (`TODO.md`), other docs link to it.

## Issue: Too many loops before enforcing one deterministic baseline
- Repeated regressions in local startup and behavior created review friction.

## Better
- Protect one golden command from day 1:
  - `make first-run-check`
  - treat it as release gate.

---

## 8) Concrete “What We Should Have Done Earlier”

1. Create `make first-run-check` in the first milestone, not late.
2. Freeze “true tool-calling agent + static FastAPI UI” as mandatory architecture early.
3. Keep Docker as baseline invariant; treat other providers as optional layers.
4. Gate MLflow and all optional integrations behind disabled-by-default flags.
5. Split CI into ordered gates before any push/build steps.
6. Publish a status map and evidence bundle before adding advanced deployment options.
7. Use profile files for Helm overrides; minimize long CLI `--set` chains.
8. Maintain a compatibility matrix for modes/providers/tests.

---

## 9) Durable Process Improvements Going Forward

- Keep `first-run-check`, runner integration, and agent integration as non-negotiable regression gates.
- Keep docs synchronized in the same patch as behavior/contract changes.
- Prefer adding one feature at a time with explicit rollback and pass/fail proof.
- Treat operational clarity (runbooks, env gates, deterministic commands) as first-class engineering work.

