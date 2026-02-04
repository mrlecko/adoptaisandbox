# REFLECTION_CHECKLIST.md

Pre-demo recursive review checklist for this project.

Use this before interview sessions, major commits, or deployment milestones.

---

## 1) Assessor Lens Drill

- [ ] If an assessor had 10 minutes to break confidence in this solution, where would they start?
- [ ] Can we proactively demonstrate resilience at those exact points?

## 2) Claim Audit

- [ ] Which README/PRD claims are backed by deterministic tests/logs?
- [ ] Which claims are still “statement only” and need evidence?

## 3) Failure-Mode Map

- [ ] What are the top 5 realistic failures (LLM, Docker, runner timeout, k8s job/RBAC, provider connectivity)?
- [ ] Do we have detection + mitigation + rollback steps for each?

## 4) Demo Script Hardening

- [ ] Is there a single 5-minute script that proves architecture, safety, and deployability?
- [ ] Does it avoid fragile/non-deterministic steps?

## 5) Security Threat Model Clarity

- [ ] Are in-scope threats clearly documented?
- [ ] Are out-of-scope risks explicitly named (to avoid overclaiming)?

## 6) Performance Truth

- [ ] What latency/concurrency numbers do we actually have?
- [ ] Are measurement method + environment documented?

## 7) Complexity Trim Pass

- [ ] What can be removed now without hurting interview signal?
- [ ] Are optional components clearly optional in docs/commands?

## 8) Maintainability Test

- [ ] Can a new agent contributor onboard from docs and deliver a small patch in <45 minutes?
- [ ] Are file ownership and “where to change X” mappings clear?

## 9) Operational Readiness

- [ ] What happens when OpenAI is unavailable?
- [ ] What happens when Docker is unavailable?
- [ ] What happens when k8s scheduling fails?

## 10) Cost / Footprint Sanity

- [ ] What is the runtime cost profile for local demo vs k8s mode?
- [ ] Are resource limits/defaults sensible and documented?

## 11) Decision Log Defensibility

- [ ] Are key tradeoffs and rejected alternatives documented?
- [ ] Can choices be defended quickly under questioning?

## 12) Post-Interview Roadmap

- [ ] Do we have the top 3 production next steps with realistic LoE and risk?
- [ ] Is there a clear boundary between “demo complete” and “prod hardening”?

---

## Exit Criteria

Before declaring “ready,” ensure:
- [ ] `make first-run-check` passes
- [ ] agent and runner core integration suites pass
- [ ] evidence docs are updated (`docs/EVIDENCE.md`)
- [ ] status map is current (`TODO.md`)

