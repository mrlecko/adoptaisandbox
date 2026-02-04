# PROBLEM_DETERMINISTIC_BASELINE.md

Status: **In Progress**  
Tier: 1  
Related plan: `TRIAGE_PLAN.md` (Stage 1)

---

## 1) Problem Identification

### Symptoms
- Local bring-up confidence was inconsistent.
- Reviewers could not rely on a single deterministic “it works” command.
- Startup/test confidence depended on manual sequences and context.

### Impact
- High demo risk.
- Slow debugging loops.
- Lower assessor trust due to reproducibility ambiguity.

---

## 2) Triage

### Likely causes
- No canonical smoke gate for startup + execution.
- Environment assumptions scattered across docs.
- Manual testing not always captured as evidence.

### Severity
- High (demo blocker class).

### Blast radius
- Local onboarding, QA, and interview walkthrough all affected.

### Rollback strategy
- If new smoke gate destabilized workflow, revert to previous manual sequence in `FIRST_RUN.md` while patching.

---

## 3) Targeted Solution

### Planned patch
- Add deterministic script: `scripts/first_run_check.sh`
- Add Make target: `make first-run-check`
- Gate must verify:
  1) server startup
  2) `/healthz`
  3) `/datasets`
  4) explicit sandboxed SQL run via `/chat`
- Add docs references:
  - `README.md`
  - `FIRST_RUN.md`
  - `AGENT_SIGNPOST.md`
  - `docs/EVIDENCE.md`

### Non-goals
- No remote/k8s validation in this stage.
- No UI visual validation in this gate (API contract only).

---

## 4) Testing

### Commands
```bash
OPENAI_API_KEY=dummy make first-run-check
agent-server/.venv/bin/pytest tests/integration/test_agent_server_singlefile.py -q
make test-runner
```

### Result summary
- Pending implementation of `make first-run-check`
- Existing baseline suites for reference:
  - `agent-server/.venv/bin/pytest tests/integration/test_agent_server_singlefile.py -q`
  - `make test-runner`

### Evidence
- To be generated under `docs/evidence/logs/` once stage is executed

---

## 5) Post-Implementation Report

### What improved
- Pending (stage not yet executed).

### Residual risks
- Current local reliability still depends on manual bring-up and ad-hoc verification.

### Re-open triggers
- Any post-implementation regression in deterministic startup/sandbox execution gate.

---

## 6) Cycle Event Log

| Timestamp | Phase | Event |
|---|---|---|
| 2026-02-03 | Problem Identification | Deterministic local baseline gap confirmed |
| 2026-02-03 | Triage | High severity; impacts demo trust and onboarding velocity |
| 2026-02-03 | Targeted Solution | Patch plan defined (script + make target + docs/evidence hooks) |
| 2026-02-03 | Testing | Command set defined; execution pending |
| 2026-02-03 | Post Report | Pending implementation and validation |
