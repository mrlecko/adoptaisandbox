# AGENT_DISCUSSION.md

## Executive Summary

This project implements a **real tool-calling ReAct-style agent** on top of FastAPI, LangChain, and LangGraph, with sandboxed SQL/Python execution against CSV datasets.

It is not just a prompt wrapper:

- It uses a graph-based agent runtime (`create_react_agent`) with explicit tools.
- It persists conversation state and run artifacts.
- It enforces multiple safety layers (SQL policy, Python AST policy, sandbox runtime limits).
- It exposes both synchronous and streaming chat APIs plus deterministic execution APIs.

For the interview scope, this is a strong and credible architecture: practical, test-backed, and extensible.

---

## 1) Core Confirmation: Is this a standard ReAct tool-calling agent?

**Yes.**

In `agent-server/app/agent.py`, `build_agent(...)` calls:

- `langgraph.prebuilt.create_react_agent(model=llm, tools=tools, prompt=system_prompt)`

That is a canonical ReAct agent pattern (reasoning + tool invocation loop) implemented through LangGraph’s prebuilt runtime.

Important nuance:

- The app also supports **explicit fast-path execution** (`SQL:` / `PYTHON:` prefixes) in `app/main.py`, which bypasses agent planning intentionally for deterministic direct execution.

So the system is both:

1. Agentic (tool-calling ReAct path), and
2. Deterministic (direct execution path when explicitly requested).

---

## 2) High-Level Stack Structure

## API / Application Layer (`app/main.py`)

- FastAPI app factory (`create_app`) + module-level `app`.
- Env-driven settings model (Pydantic).
- Routes:
  - `POST /chat` (sync chat)
  - `POST /chat/stream` (SSE streaming chat)
  - `POST /runs` (deterministic execution endpoint)
  - `GET /runs/{id}`, `GET /runs/{id}/status`
  - `GET /threads/{thread_id}/messages`
  - `GET /datasets`, `GET /datasets/{dataset_id}/schema`
  - `GET /healthz`, `GET /metrics`, `GET /` (static UI)

## Agent Layer (`app/agent.py`)

- System prompt rules + ReAct graph construction.
- Session orchestration:
  - history load
  - prior-run context injection
  - agent invoke / stream invoke
  - output extraction
  - persistence to message store + run capsules

## Tool Layer (`app/tools.py`)

Five tools:

1. `list_datasets`
2. `get_dataset_schema`
3. `execute_sql`
4. `execute_query_plan`
5. `execute_python`

Execution tools call a shared helper (`execute_in_sandbox`).

## Validation / Compilation Layer

- `validators/sql_policy.py`: SQL allow/block checks + dataset prefix normalization.
- `validators/compiler.py`: QueryPlan DSL -> deterministic DuckDB SQL.
- `models/query_plan.py`: typed DSL schema and validation rules.

## Sandboxing Layer

- Provider factory (`executors/factory.py`) selects:
  - Docker executor
  - MicroSandbox executor
  - K8s Job executor
- Shared runner contract through JSON stdin/stdout.

## Storage Layer

- SQLite run capsule persistence (`storage/capsules.py`).
- Pluggable message-store abstraction; currently SQLite (`storage/messages.py`).

## UI Layer

- Single static HTML/JS client (`app/static/index.html`).
- Streams `/chat/stream` and renders:
  - conversational thread (left panel),
  - result table + details JSON (right panel).

## Observability Layer

- Structured logs + request IDs.
- Prometheus counters/histograms.
- Optional MLflow tracing/autolog + trace metadata (`user_id`, `thread_id`).

---

## 3) Request Flow Deep Dive

## A) `/chat` flow

1. Parse request and derive `thread_id`, `input_mode`.
2. If message starts with:
   - `SQL:` -> direct deterministic SQL execution (`_execute_direct`)
   - `PYTHON:` -> direct deterministic Python execution (`_execute_direct`)
3. Else use ReAct agent path (`session.run_agent(...)`).
4. Persist outputs (messages + capsules), increment metrics, return response contract.

## B) `/chat/stream` flow

1. Same mode detection (fast path vs agent path).
2. Fast path emits synthetic SSE stages + final result.
3. Agent path emits:
   - status events
   - token events
   - tool_call / tool_result events
   - final result + done
4. Converts non-JSON event payloads with `default=str` to avoid serialization failures.

## C) `/runs` flow (non-agent deterministic API)

- Accepts explicit `query_type` (`sql|python|plan`).
- Applies same policy/compilation/execution stack.
- Persists capsule and returns normalized response.

This endpoint is useful for deterministic integration and deployment smoke checks.

---

## 4) Agent Behavior and Memory Model

The agent is stateful at thread level, but with a practical bounded memory strategy:

- Message history comes from SQLite message store.
- Windowed history (`thread_history_window`, default 12).
- Additional prior-run context is injected from the most recent successful capsule in same thread/dataset:
  - query mode
  - row count
  - columns
  - SQL snippet
  - Python snippet

This allows follow-up requests like:

- “those again but with product name”

without needing full LangGraph checkpointer infrastructure.

---

## 5) Tool-Calling and Result Extraction Details

The implementation stores tool outputs as JSON strings and later reconstructs run metadata by walking message history:

- It maps `tool_call_id -> tool_name` from AI messages.
- It only treats outputs from execution tools as result-bearing (`execute_sql`, `execute_query_plan`, `execute_python`).
- It derives:
  - `query_mode`
  - `compiled_sql`
  - `plan_json`
  - `python_code`
  - final status + result payload

This gives clear capsule lineage but introduces one known fragility:

- If model/tool output format drifts, extraction can degrade (still generally handled with safe defaults).

---

## 6) Safety and Guardrails: Layered Controls

## SQL guardrails

- Accept only `SELECT`/`WITH`.
- Reject multi-statement.
- Blocklist dangerous tokens (DDL/DML, file-read functions, pragma-like ops).
- Normalize dataset-qualified table refs.

## QueryPlan guardrails

- Strong typed schema validation.
- Deterministic compiler.
- Identifier/value escaping.
- Group-by + aggregation consistency rules.

## Python guardrails

- AST policy:
  - restricted imports
  - blocked modules/calls
  - blocked write/export methods
  - blocked dunder access
- Reduced builtin surface for execution.
- Result conversion contract (`result_df`, `result_rows`, `result`, etc.).

## Runtime sandbox guardrails

Docker path currently enforces:

- no network
- read-only rootfs
- read-only data mount
- memory/cpu/pids limits
- tmpfs scratch

All paths still rely on sandbox boundary as critical defense-in-depth.

---

## 7) Observability and Traceability

## Included now

- HTTP metrics + latency histograms.
- Agent turn counters by mode/status.
- Sandbox run counters by provider/query mode/status.
- Structured JSON logs with request/thread/run IDs.
- Optional MLflow:
  - global OpenAI autolog (when enabled)
  - per-turn tracing wrapper
  - user/session metadata:
    - `mlflow.trace.user`
    - `mlflow.trace.session`

## Operational value

- You can correlate user messages -> tool calls -> run capsule -> execution status.
- You can inspect run details through `/runs/{id}` and thread history through `/threads/{id}/messages`.

---

## 8) Capability Summary (What the Agent Can Do Today)

1. Conversational chat (general + data-oriented).
2. Tool-based dataset discovery and schema retrieval.
3. Agent-generated SQL execution for data questions.
4. Structured QueryPlan execution (via compile + execute).
5. Python/pandas execution in sandbox (explicit and tool-driven).
6. Stateful follow-up within thread context.
7. Streaming output for UI (tokens/tools/result events).
8. Provider-switchable sandbox backends (docker/microsandbox/k8s).

---

## 9) Known Limitations / Design Tradeoffs

## Agent/runtime limitations

- Uses deprecated LangGraph prebuilt API symbols (works now; migration needed later).
- One streaming integration case is currently skipped in tests due intermittent hang.
- Agent behavior still depends on model compliance with prompt/tool strategy.

## Safety limitations

- SQL policy is denylist-based; denylist can miss edge cases.
- Python restrictions are strong for this scope but still rely on defense-in-depth from sandboxing.
- No dedicated policy engine (OPA/Cedar/rego) yet.

## Scale/ops limitations

- SQLite is fine for demo/single-node; not ideal for high concurrency HA.
- Executor runtime status caches are process-local.
- No distributed queue for long-running jobs.

## Product limitations

- No RBAC/tenant partitioning yet.
- No explicit rate-limits or abuse controls in API layer.
- UI is intentionally minimal; not a production-grade chat client.

---

## 10) Sanity Check and Architecture Review

## What is solid

1. **Correct architectural decomposition** (API, agent, tools, execution, storage, validation).
2. **Legitimate agent implementation** (ReAct graph + real tools).
3. **Strong interview-relevant hardening mindset** (sandboxing + policy layers + tests).
4. **Pragmatic dual-path UX** (deterministic fast path + agent path).
5. **Clear observability hooks** (metrics/logs/MLflow trace metadata).

## What should be improved next

1. **Streaming reliability**: resolve flaky stream test root cause and remove skip.
2. **LangGraph API migration**: move off deprecated imports before ecosystem breaking changes.
3. **Policy rigor**: move from simple blocklists toward stricter allowlist/parsing strategy.
4. **Production state model**: externalize transient run state and strengthen storage backend.
5. **Execution control plane**: queue/job orchestration for robust high-load behavior.

---

## 11) Final Assessment

For the stated interview objective (agent + basic UI + sandboxed CSV query execution), this implementation is:

- **Architecturally sound**
- **Functionally complete**
- **Security-conscious for PoC/demo scope**
- **Well positioned for production hardening**

The most important strategic point: this codebase already demonstrates the right engineering instincts (modularity, guardrails, observability, test coverage, provider abstraction). Remaining gaps are mostly maturity/hardening tasks, not conceptual rewrites.

