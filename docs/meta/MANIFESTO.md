# MANIFESTO.md

## Agentic Iteration Manifesto

### 1) Why we do this
We are not optimizing for one-off completion.  
We are optimizing for **compounding iteration speed with preserved correctness**.

Progress is not "more code."  
Progress is **better handovers, lower uncertainty, and faster safe loops**.

---

### 2) North Star
**Improve the system while making the next iteration cheaper, safer, and clearer.**

If a change ships but makes future work harder, it is not progress.

---

### 3) Shared Reward Function
Humans and agents are rewarded for:

1. **Determinism**  
   Core path remains reproducible (`make first-run-check` or equivalent).

2. **Correctness with proof**  
   Claims are backed by tests and evidence logs.

3. **Transferability**  
   A new contributor can continue without hidden context.

4. **Risk reduction**  
   Ambiguity, drift, and fragile assumptions are actively removed.

---

### 4) Unit of Work: The Loop
Every meaningful change follows this loop:

1. Problem Identification
2. Triage (scope, severity, blast radius)
3. Targeted Solution (minimal patch)
4. Testing (tactical then regression)
5. Evidence Capture
6. Post-Implementation Report
7. Handover Contract

If any step is missing, the loop is incomplete.

---

### 5) Definition of Done
A task is done only when it includes:

- Code change
- Test verification
- Evidence artifact(s)
- Status/documentation update
- Clear next-step handover

No proof, no done.

---

### 6) Anti-Goals
We reject:

- Silent behavior changes
- Contract drift without tests/docs updates
- "Works locally" claims without evidence
- Optional integrations that can break baseline startup
- Feature expansion that weakens baseline reliability

---

### 7) Baseline Invariant
There must always be one canonical, deterministic success path.

In this project, that path is the local baseline flow and its validation command(s).  
All optional capabilities are additive and must never regress that baseline.

---

### 8) Handover Contract (Minimum)
Every handover must state:

- What changed
- What passed (commands + outcomes)
- Residual risks
- Exact next action

This is the minimum semantic payload for continuity.

---

### 9) Source-of-Truth Rule
Status has one owner.  
Requirements have one owner.  
Evidence has one owner.

If ownership is plural, truth is ambiguous.

---

### 10) Statement of Progress
**Plugging into the shared knowledge pipeline _is_ progress.**

When work leaves behind clear intent, verified outcomes, and usable handoff context,  
the system improves even before the next line of code is written.

