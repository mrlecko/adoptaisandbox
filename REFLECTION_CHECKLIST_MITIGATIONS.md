# REFLECTION_CHECKLIST_MITIGATIONS.md

Q/A mitigation guide for the reflection checklist questions.

Goal: convert high-value review questions into direct, practical actions.

---

## 1) Assessor Lens Drill

**Q:** If an assessor had 10 minutes to break confidence, where would they poke first?  
**A:** They will likely test startup reliability, execution safety, and result grounding.  
**Mitigation:**
- Keep `make first-run-check` green and demo it first.
- Run one explicit SQL query path that proves real sandbox execution.
- Show evidence logs, not just screenshots.

---

## 2) Claim Audit

**Q:** Which claims are unproven?  
**A:** Anything not tied to a repeatable command + pass/fail output.  
**Mitigation:**
- For every public claim in README/PRD summary, add:
  - validating command
  - expected output
  - log reference in `docs/EVIDENCE.md`.

---

## 3) Failure-Mode Map

**Q:** What realistic failures matter most?  
**A:** LLM outage, Docker unavailable, sandbox timeout, policy rejection, k8s job/RBAC failure.  
**Mitigation:**
- Build a failure table with columns: symptom / detection / user-facing message / recovery command.
- Validate each failure path once and archive logs.

---

## 4) Demo Script Hardening

**Q:** How do we avoid fragile demos?  
**A:** Use deterministic, pre-validated flows only.  
**Mitigation:**
- Use fixed query examples with known output shapes.
- Avoid optional components during core demo (e.g., MLflow unless explicitly needed).
- Keep a 5-minute “minimum successful narrative” script.

---

## 5) Security Threat Model

**Q:** What threats should we discuss confidently?  
**A:** Prompt-led unsafe SQL/Python, exfil attempts, resource abuse, unsafe execution location.  
**Mitigation:**
- Document in-scope controls (policy validation, sandbox isolation, limits).
- Document out-of-scope items (full multi-tenant auth, enterprise secrets lifecycle).
- Ensure security test fixtures map to threat statements.

---

## 6) Performance Truth

**Q:** What performance claims are safe to make?  
**A:** Only measured claims with environment context.  
**Mitigation:**
- Capture baseline response times for canonical prompts.
- Separate local vs k8s numbers.
- Avoid hard SLA statements unless repeatedly validated.

---

## 7) Complexity Trim

**Q:** What should we cut or de-emphasize?  
**A:** Anything that adds risk without adding interview signal.  
**Mitigation:**
- Keep Docker path as default.
- Treat MicroSandbox and advanced telemetry as optional profiles.
- Remove or clearly mark partial/placeholder targets.

---

## 8) Maintainability Test

**Q:** Can a new agent contribute quickly?  
**A:** Only if onboarding docs are task-oriented and file-mapped.  
**Mitigation:**
- Keep `AGENT_SIGNPOST.md` current.
- Include “change routing” sections (where to edit X).
- Add one simple “first patch” exercise and expected test command.

---

## 9) Operational Readiness

**Q:** What if dependencies are down?  
**A:** Degrade gracefully and fail with clear diagnostics.  
**Mitigation:**
- LLM unavailable: deterministic fallback/error message.
- Docker unavailable: explicit preflight failure and command guidance.
- k8s scheduling/RBAC fail: runbook with exact kubectl checks and remediations.

---

## 10) Cost / Footprint

**Q:** How to answer “what does this cost to run”?  
**A:** Provide bounded, practical estimates and defaults.  
**Mitigation:**
- Document resource defaults for runner/server.
- Give one local and one k8s profile with expected small-demo footprint.
- Clarify which features materially increase cost (tracing, extra providers).

---

## 11) Decision Log Defensibility

**Q:** Can we defend architectural choices under pressure?  
**A:** Yes, if tradeoffs are explicit and tied to requirements.  
**Mitigation:**
- For each key decision, record:
  - alternatives considered
  - why rejected
  - what would change the decision later.

---

## 12) Post-Interview Roadmap

**Q:** What are pragmatic next steps after demo acceptance?  
**A:** Prioritize reliability, security depth, and deployability proof.  
**Mitigation:**
- Keep top 3 roadmap items:
  1) live-cluster hardening + CI k8s smoke
  2) stricter SQL parsing/validation
  3) measured perf/concurrency baselines.
- Attach LoE + risk + expected value per item.

---

## Compact Action Plan (Reusable)

Before each major checkpoint:
1. Run deterministic baseline (`make first-run-check`).
2. Re-run agent + runner integration suites.
3. Update evidence logs.
4. Reconcile README/TODO/PRD status references.
5. Review top 3 known risks and demo mitigation narrative.

