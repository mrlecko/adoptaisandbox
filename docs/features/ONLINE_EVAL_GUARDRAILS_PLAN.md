# Online Eval + Guardrails Plan

**Date:** 2026-02-03  
**Status:** In progress (Phase 0 mostly complete)  
**Scope:** Agent-server runtime quality controls for live traffic

---

## 1) Objectives

1. Add **online evals** for live conversations (quality + policy).
2. Add **runtime guardrails** before/after tool execution.
3. Improve **hardening** (abuse resistance, reliability, rollback safety).
4. Keep rollout low-risk and incremental (no regressions to docker runner path).

---

## 2) Non-Goals (for this plan)

- Offline benchmark framework redesign (MLflow already covers offline tracing/evals).
- Full SIEM/SOC integration.
- Multi-tenant auth/entitlements redesign.

---

## 3) Phased Delivery (Concrete Checklist)

## Phase 0 — Baseline Instrumentation (0.5 day)

- [x] Add per-request correlation ids (request_id, thread_id, run_id) in server logs.
- [x] Emit structured JSON logs for `/chat`, `/chat/stream`, `/runs`.
- [x] Add metrics primitives (counter/histogram/gauge) and `/metrics` endpoint.
- [ ] Add dashboard starter panel (latency, errors, tool calls, timeout rate).

_Note: dashboard composition is intentionally left for Grafana/Prometheus wiring in the next increment._

**Acceptance Criteria**
- Every request log line includes request_id + thread_id.
- `/metrics` exposes endpoint latency and status-code counters.
- Can trace one user turn end-to-end across logs + MLflow trace + capsule.

---

## Phase 1 — Online Eval Pipeline (1 day)

- [ ] Implement async evaluator worker (non-blocking to user response path).
- [ ] Persist `online_eval_results` keyed by run_id + thread_id + timestamp.
- [ ] Evaluate every turn (or sampled turns) with:
  - [ ] `intent_resolution` (did answer match intent)
  - [ ] `tool_appropriateness` (tool call made only when needed)
  - [ ] `groundedness_to_result` (claims supported by result payload)
  - [ ] `policy_compliance` (no disallowed SQL/Python behavior)
- [ ] Add configurable sampling rate (`ONLINE_EVAL_SAMPLE_RATE`).

**Acceptance Criteria**
- Eval worker failures never break chat responses.
- At least 3 eval dimensions stored for sampled turns.
- Dashboard shows quality score trend over time.

---

## Phase 2 — Guardrails (1–1.5 days)

### 2.1 Pre-Agent Guardrails
- [ ] Add intent classifier: `chat_only | data_query | disallowed`.
- [ ] Block tools for `chat_only`; allow normal conversation response.
- [ ] Reject `disallowed` with safe refusal template.

### 2.2 Pre-Execution Guardrails
- [ ] Add SQL AST validation (read-only + schema allowlist).
- [ ] Enforce dataset table/column allowlists from registry schema.
- [ ] Add tool budget controls:
  - [ ] max tool calls/turn
  - [ ] max retries
  - [ ] max wall-clock planning time

### 2.3 Post-Execution Guardrails
- [ ] Add response-grounding check:
  - [ ] scalar results must be referenced directly in assistant response
  - [ ] large/tabular results require explicit “see result table” reference
- [ ] Detect and flag hallucinated numeric claims not present in result rows.

**Acceptance Criteria**
- Prompt-injection and schema-bypass tests fail closed.
- Recursion/error loops terminate with deterministic safe response.
- No increase in successful forbidden-query executions (target: 0).

---

## Phase 3 — Hardening + SLO Controls (1 day)

- [ ] Add per-user/IP rate limits for chat endpoints.
- [ ] Add concurrent run caps + queue depth controls.
- [ ] Add LLM provider circuit breaker + fallback behavior.
- [ ] Add alert thresholds:
  - [ ] timeout rate spike
  - [ ] policy violation spike
  - [ ] recursion-limit spike
  - [ ] eval quality drop
- [ ] Add canary deployment gates using online eval score + error budgets.

**Acceptance Criteria**
- Load test with controlled degradation (no cascading failure).
- Canary auto-hold when eval quality or policy metrics regress.
- Rollback runbook validated once in staging.

---

## 4) Data Model Additions

### `online_eval_results` (new table)
- `id` (pk)
- `created_at`
- `run_id`
- `thread_id`
- `dataset_id`
- `request_id`
- `evaluator_version`
- `scores_json` (per-dimension score + rationale)
- `flags_json` (policy/hallucination/guardrail flags)

### Optional `guardrail_events` (new table)
- `id`, `created_at`, `request_id`, `thread_id`, `event_type`, `details_json`

---

## 5) Config Additions

- `ONLINE_EVAL_ENABLED=true|false`
- `ONLINE_EVAL_SAMPLE_RATE=0.2`
- `ONLINE_EVAL_ASYNC_WORKERS=2`
- `GUARDRAIL_MAX_TOOL_CALLS=4`
- `GUARDRAIL_MAX_RETRIES=2`
- `GUARDRAIL_MAX_PLAN_SECONDS=8`
- `RATE_LIMIT_RPM=60`
- `MAX_CONCURRENT_RUNS=20`

---

## 6) Test Plan (TDD)

- [ ] Unit tests: evaluator scoring, guardrail decisions, AST policy.
- [ ] Integration tests:
  - [ ] normal conversation (no unnecessary tool call)
  - [ ] valid SQL query path
  - [ ] forbidden SQL blocked
  - [ ] hallucinated answer detection
  - [ ] recursion-loop termination path
- [ ] Chaos/failure tests:
  - [ ] evaluator worker down
  - [ ] MLflow unavailable
  - [ ] LLM provider timeout spikes

---

## 7) Rollout Strategy

1. Ship Phase 0 + Phase 1 in **observe-only** mode (no user-facing blocks).
2. Enable Phase 2 guardrails in **shadow mode** (log-only decisions).
3. Turn on blocking gradually (10% → 50% → 100%).
4. Enable Phase 3 SLO gates + canary checks.

---

## 8) Effort Summary

- Phase 0: **0.5 day**
- Phase 1: **1 day**
- Phase 2: **1–1.5 days**
- Phase 3: **1 day**

**Total:** ~**3.5–4 days** for a strong production-ready first cut.
