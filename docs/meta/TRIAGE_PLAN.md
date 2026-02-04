# TRIAGE_PLAN.md

Protocol and execution plan for efficient agentic refinement loops:

**problem -> triage -> targeted solution -> testing -> post-implementation report -> repeat**

Semantic foundation:
- `MANIFESTO.md` (shared human+agent intention/reward/protocol)

---

## 1) Objective

Create a repeatable protocol that lets human + agent move quickly without losing rigor, by making every iteration:
- scoped
- testable
- evidenced
- documented

This plan defines **Tier 1** issues (highest immediate impact on demo reliability and assessor trust).

---

## 2) Triage Loop Protocol (v1)

For each problem stage, use exactly this cycle:

1. **Problem Identification**
   - symptom(s)
   - impact/risk
   - reproduction path
2. **Triage**
   - likely root cause(s)
   - severity
   - blast radius
   - rollback strategy
3. **Targeted Solution**
   - minimal patch set
   - non-goals (avoid scope creep)
4. **Testing**
   - tactical tests first
   - regression suites second
   - evidence log capture
5. **Post-Implementation Report**
   - what changed
   - what passed
   - residual risk
   - next trigger for re-open

**Hard rule:** do not advance stage N+1 until stage N has evidence and a written post-report.

---

## 3) Tier 1 Stages (Immediate)

## Stage 1: Deterministic Baseline Execution
- Goal: one command proves local startup + sandbox execution.
- Owner artifact: `docs/features/PROBLEM_DETERMINISTIC_BASELINE.md`
- Exit criteria:
  - `make first-run-check` passes
  - evidence logs recorded

## Stage 2: Status Source-of-Truth Consistency
- Goal: eliminate status drift across README/TODO/PRD.
- Owner artifact: `docs/features/PROBLEM_STATUS_SOURCE_OF_TRUTH.md`
- Exit criteria:
  - TODO declared canonical
  - README + PRDs aligned and explicit

## Stage 3: Failure-Mode Readiness
- Goal: top operational failures have deterministic diagnosis + mitigation.
- Owner artifact: `docs/features/PROBLEM_FAILURE_MODE_READINESS.md`
- Exit criteria:
  - top 5 failure modes documented with commands
  - at least 2 validated with reproducible outputs

---

## 4) Stage Status Board

| Stage | Status | Evidence |
|---|---|---|
| Stage 1 - Deterministic Baseline | In progress | `docs/EVIDENCE.md`, `docs/evidence/logs/*` |
| Stage 2 - Status Source-of-Truth | In progress | README/TODO/PRD alignment patches |
| Stage 3 - Failure-Mode Readiness | Planned | runbook matrix + targeted checks |

---

## 5) Commands to Reuse During Tier 1

```bash
make first-run-check
agent-server/.venv/bin/pytest tests/integration/test_agent_server_singlefile.py -q
make test-runner
agent-server/.venv/bin/pytest tests/unit -q
agent-server/.venv/bin/pytest tests/security -q
```

Evidence capture target:
- `docs/EVIDENCE.md`
- `docs/evidence/logs/`

---

## 6) Definition of Tier 1 Completion

Tier 1 is complete when:
- all three Stage docs have full cycle sections filled
- stage statuses are `Completed`
- evidence file links are present and valid
- no contradiction exists between README and TODO status map
