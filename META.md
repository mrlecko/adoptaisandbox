# META.md

Retrospective + meta-specification guide for building this project faster with fewer loops.

---

## 0) Why this document exists

This repository reached a strong end-state, but through many iterative loops.  
This document answers:

1. What happened in practice (from commit/process history)?
2. What requirement framing would have converged faster?
3. What reusable patterns help for future fully agentic implementation?

This is both a postmortem and a forward-looking playbook.

---

## 1) What the process history actually shows

From the commit trajectory, development moved through these waves:

1. **Bootstrapping foundation**  
   datasets → DSL/compiler → runner image → first server.
2. **Stability and correctness loops**  
   structured-output parsing, SQL policy false positives, timeout handling, test reliability.
3. **Feature expansion loops**  
   Python sandbox mode, stateful conversation, UI behavior, result formatting.
4. **Architecture upgrade loop**  
   from “planner-like endpoint” to a real tool-calling agent.
5. **Execution backend expansion loop**  
   Docker baseline → MicroSandbox option → K8s Job executor.
6. **Ops/deployment loop**  
   Helm chart, local k8s bring-up, image pull/policy/RBAC/friction.
7. **Observability loop**  
   MLflow integration, session metadata, gating/tracing stability.
8. **Interview hardening loop**  
   first-run determinism, evidence bundle, status normalization, CI gating.

### Key pattern in the loops

Most loops were not “bad code” loops; they were **contract-ambiguity loops**:
- What is the canonical architecture?
- What is the primary demo path?
- Which behavior is hard requirement vs nice-to-have?
- What is the “source of truth” for status?
- What exact tests gate progression?

---

## 2) Gap analysis: initial PRD intent vs delivered system

## What the PRD got right
- Strong emphasis on safe sandbox execution.
- Clear need for local + k8s deployment.
- Emphasis on auditability (run capsules).
- Useful framing of MVP vs stretch.

## Where initial requirements were under-specified

1. **Primary interaction architecture was ambiguous**
   - “stock LangChain UI” vs lightweight in-app static UI.
   - LangChain classic server vs LangGraph runtime assumptions.

2. **No frozen “golden path” early**
   - Without one deterministic startup/smoke, every feature addition carried integration risk.

3. **No explicit execution mode matrix**
   - SQL direct, plan-compiled SQL, explicit Python, implicit Python.
   - This caused behavior inconsistencies and parser/tool-call edge cases.

4. **No CI parity contract**
   - Python version, black/ruff scope, image tags, test image lifecycle not frozen up front.

5. **No explicit “status source of truth” policy**
   - README/TODO/PRD drift became likely and happened.

6. **Telemetry introduced before hard gating**
   - MLflow integration created startup fragility until feature-gated.

---

## 3) The requirement prompt that would have converged faster

If we had to restart, this is the initial prompt/spec I would use (project-specific):

---

### Recommended Initial Requirement Prompt (for this repo)

Build a production-minded demo system called **CSV Analyst Chat** with these strict constraints:

1. **Architecture freeze (non-negotiable)**
   - Single FastAPI server (`agent-server/app/main.py`) serving:
     - static chat UI (`GET /`)
     - API (`/chat`, `/chat/stream`, `/runs`, `/datasets`, `/healthz`, `/metrics`)
   - Agent must be a **real tool-calling agent** (LangChain/LangGraph acceptable).
   - Model never executes data logic directly; execution only via tools + sandbox executor.

2. **Execution freeze (non-negotiable)**
   - Default sandbox: Docker (`SANDBOX_PROVIDER=docker`).
   - Runner image supports SQL and restricted Python via separate entrypoints.
   - Feature-gate Python (`ENABLE_PYTHON_EXECUTION`).
   - Any optional provider (MicroSandbox/K8s) must not regress Docker path.

3. **Golden path freeze (non-negotiable)**
   - Add `make first-run-check` on day 1.
   - It must pass/fail deterministically and verify:
     - server start
     - dataset endpoint
     - one explicit SQL run executed in sandbox
   - Every change must preserve this command.

4. **Test gating order (non-negotiable)**
   - Unit + security first.
   - Agent integration second.
   - Docker runner/executor integration third.
   - CI image build only after all above pass.

5. **Docs/source-of-truth policy (non-negotiable)**
   - `TODO.md` is canonical implementation status.
   - PRD files define requirements only.
   - README summarizes and links to TODO + evidence.

6. **Observability policy**
   - Add logs/metrics first.
   - Add tracing (MLflow) only behind `MLFLOW_ENABLED` hard gate default false.
   - Tracing failures must never block server startup.

7. **Definition of done for each feature**
   Every feature PR must include:
   - code change
   - test(s)
   - Make command impact (if any)
   - docs update
   - explicit regression statement for Docker default path.

8. **Deployment acceptance**
   - Local path: pass `make first-run-check`.
   - K8s path: pass `make k8s-smoke` + `make k8s-test-runs`.
   - Provide evidence log artifacts under `docs/evidence/logs`.

Output:
- implementation
- updated docs
- evidence bundle
- CI workflow reflecting these gates

---

Why this is better:
- It encodes constraints as enforceable contracts, not aspirations.
- It minimizes branching ambiguity (UI type, agent type, provider precedence).
- It introduces deterministic proof early.

---

## 4) Design patterns that worked (and should be explicit earlier)

## Pattern A: **Execution boundary pattern**
“Planner in process, execution out of process.”
- Keep LLM orchestration and compute execution separate.
- Use strict tool interfaces and normalized result envelopes.

## Pattern B: **Provider abstraction pattern**
- `Executor` interface + factory by `SANDBOX_PROVIDER`.
- Docker as baseline invariant; optional providers must preserve baseline.

## Pattern C: **Mode gating pattern**
- Explicit modes (`SQL:`, `PYTHON:`) + feature flags.
- Prefer explicit mode first; add implicit mode once explicit path is stable/tested.

## Pattern D: **Deterministic evidence pattern**
- Every major claim (works, secure, deployed) should have a reproducible command and log artifact.

## Pattern E: **Status single-writer pattern**
- Exactly one file owns implementation truth (`TODO.md`).
- Other docs link to it, not duplicate status.

## Pattern F: **Progressive hardening pattern**
1. correctness
2. regression tests
3. ops hooks
4. deployment hardening
5. polish

---

## 5) Fast paths that would have saved time

1. **Freeze and defend one local baseline**
   - Docker sandbox path is the baseline.
   - Any advanced feature (MicroSandbox, K8s, tracing) is additive and optional.

2. **Run tactical tests, not broad tests, during active patching**
   - target module tests first
   - relevant integration file second
   - full suite later

3. **Treat Makefile as product interface**
   - human and agent both depend on reliable command ergonomics.
   - stubs should be clearly marked or implemented quickly.

4. **Gate optional infrastructure features from startup path**
   - tracing/telemetry should degrade gracefully.

5. **Commit “workflow correctness” alongside feature code**
   - CI mismatch can erase feature value by creating trust debt.

---

## 6) Pragmatic heuristics (meta advice)

## “Specify invariants, not intentions.”
Examples for this project:
- “All compute goes through executors” is an invariant.
- “We prefer safe execution” is an intention.

## “Every new axis adds a matrix.”
Adding Python + MicroSandbox + K8s multiplies test paths.  
Control this with explicit support matrix and gating order.

## “Golden path first, breadth second.”
Lock one deterministic journey before adding optional backends or UX polish.

## “If it can block startup, it must be gated.”
Tracing, remote services, and optional providers must be opt-in, not startup-critical.

## “Docs are part of runtime correctness.”
In an interview demo, stale docs are functional bugs.

---

## 7) Aphorisms for agentic build systems

- “A demo is a product with a shorter half-life.”
- “Unclear ownership creates retry loops.”
- “Features without proof are hypotheses.”
- “Optional dependencies are mandatory failure points unless gated.”
- “A green CI is a narrative, not just a checkmark.”
- “Regression prevention is cheaper than feature rediscovery.”
- “If the first command is not deterministic, the rest is theater.”

---

## 8) A reusable implementation checklist template (for future projects)

Use this for any similar AI + sandbox + deployment build:

1. **Architecture lock**
   - service boundaries
   - execution boundary
   - persistence boundary
2. **Baseline lock**
   - one deterministic local run command
   - one deterministic smoke assertion
3. **Contract tests**
   - API contract tests
   - execution contract tests
   - security-policy contract tests
4. **Provider expansion**
   - interface + factory + parity tests
5. **Ops hooks**
   - health + metrics + request IDs
6. **Optional observability**
   - explicit gate and graceful degradation
7. **Deployment track**
   - local k8s + remote k8s runbook
8. **Evidence**
   - reproducible logs
   - status map
   - CI gate map

---

## 9) What to preserve in this repo going forward

1. Keep `make first-run-check` green at all times.
2. Keep Docker path as non-regression baseline.
3. Keep TODO as canonical status source.
4. Keep `docs/EVIDENCE.md` updated after major changes.
5. Keep CI gate order aligned with practical risk:
   - lint/core tests → docker integration → image build.

---

## 10) Final takeaway

The end-state is strong and interview-worthy.  
The acceleration opportunity was not “coding faster”; it was **specifying sharper invariants and faster proof loops** earlier.

In agentic systems, clarity of contracts beats volume of instructions.

