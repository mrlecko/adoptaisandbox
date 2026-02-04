# PROBLEM_FAILURE_MODE_READINESS.md

Status: **Planned**  
Tier: 1  
Related plan: `TRIAGE_PLAN.md` (Stage 3)

---

## 1) Problem Identification

### Symptoms
- Core runtime paths exist, but failure-handling narrative is fragmented across logs/tests/docs.
- Operators/new agents may know *that* something failed but not the fastest mitigation command.

### Impact
- Slower incident triage during demos.
- Increased perceived fragility under assessor probing.

### Priority failure modes
1. Missing LLM key / provider misconfig
2. Docker daemon unavailable
3. SQL policy rejection confusion
4. Runner timeout / resource exceeded
5. K8s Job execution/RBAC failure (when in k8s mode)

---

## 2) Triage

### Likely causes
- Failure behavior is implemented but not centrally expressed as a diagnosis matrix.
- Mitigation commands live in several docs/runbooks.

### Severity
- High for demo resilience and operations confidence.

### Blast radius
- Local and k8s troubleshooting flow.

### Rollback strategy
- None required for doc-only stage; risk is informational incompleteness.

---

## 3) Targeted Solution

### Planned patch
- Create a compact failure-mode table with:
  - symptom
  - probable cause
  - immediate check command
  - mitigation command
  - expected recovery signal
- Link table from:
  - `README.md`
  - `FIRST_RUN.md`
  - `docs/runbooks/K8S_HELM_DOCKER_RUNBOOK.md`
- Validate at least 2 failure modes with reproducible command/output snippets.

### Non-goals
- No new runtime code changes in this stage unless a critical gap is discovered.

---

## 4) Testing

### Planned validation commands

Example checks to execute and log:
```bash
# Missing key path
unset OPENAI_API_KEY ANTHROPIC_API_KEY
make first-run-check

# Docker unavailable path (simulate/verify explicit preflight behavior)
make local-preflight

# SQL policy rejection path
curl -sS -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  --data-binary '{"dataset_id":"support","message":"SQL: DROP TABLE tickets"}'
```

### Expected outcomes
- Deterministic, user-readable failures with direct remediation.
- Runbook and docs point to exact commands.

### Evidence target
- `docs/evidence/logs/` with dedicated failure-mode logs.

---

## 5) Post-Implementation Report

### What improved
- Pending stage execution.

### Residual risks
- If not completed, demo still depends on ad-hoc troubleshooting skill.

### Re-open triggers
- Any observed failure case lacking a one-command diagnosis + remediation.

---

## 6) Cycle Event Log

| Timestamp | Phase | Event |
|---|---|---|
| 2026-02-03 | Problem Identification | Failure-mode handling identified as fragmented |
| 2026-02-03 | Triage | High importance for assessor confidence under probing |
| 2026-02-03 | Targeted Solution | Failure-matrix patch plan defined |
| 2026-02-03 | Testing | Validation command set drafted |
| 2026-02-03 | Post Report | Pending implementation |

