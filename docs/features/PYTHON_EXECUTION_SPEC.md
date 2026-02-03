# Python Execution Specification (Same Runner Image, Separate Entrypoint)

## 1) Goal

Extend the current sandbox runner to support arbitrary (but constrained) Python analysis in addition to SQL, while preserving deployment simplicity:

- Keep **one runner Docker image**.
- Use **separate entrypoints** for SQL and Python execution.
- Keep the same sandbox/runtime controls already used for SQL.

---

## 2) Scope

### In Scope
- New Python execution path in runner.
- Runner request/response schema extension for `query_type=python`.
- Agent-server tooling to invoke Python runner entrypoint.
- Guardrails: AST policy checks, import restrictions, output limits, timeout handling.
- Run capsule support for Python metadata.
- Tests (unit + integration + security).

### Out of Scope (First Iteration)
- Multi-turn stateful Python sessions.
- Arbitrary package installation at runtime.
- File writes/persistence from Python code.
- Chart/image generation pipeline.

---

## 3) High-Level Design

Single image, two executables:

- SQL path (existing): `python3 /app/runner.py`
- Python path (new): `python3 /app/runner_python.py`

Agent server chooses entrypoint based on query type:
- `query_type=sql` -> SQL entrypoint
- `query_type=python` -> Python entrypoint

Both run under the same Docker sandbox flags:
- `--network none`
- `--read-only`
- `--pids-limit 64`
- `--memory 512m --cpus 0.5`
- `--tmpfs /tmp:rw,noexec,nosuid,size=64m`
- datasets mounted read-only at `/data`

---

## 4) Runner Contract Changes

## 4.1 RunnerRequest

Add fields:

```json
{
  "query_type": "sql | python",
  "dataset_id": "support",
  "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
  "sql": "SELECT ...",
  "python_code": "import pandas as pd ...",
  "timeout_seconds": 10,
  "max_rows": 200,
  "max_output_bytes": 65536
}
```

Rules:
- `query_type=sql` requires `sql`.
- `query_type=python` requires `python_code`.
- `sql` and `python_code` are mutually exclusive in first iteration.

## 4.2 RunnerResponse

Keep current envelope for compatibility:

```json
{
  "status": "success | error | timeout",
  "columns": ["..."],
  "rows": [["..."]],
  "row_count": 1,
  "exec_time_ms": 42,
  "stdout_trunc": "",
  "stderr_trunc": "",
  "error": null
}
```

Add optional metadata:
- `query_type`
- `resource_usage` (future)

---

## 5) Entrypoint Strategy (Same Image)

## 5.1 Dockerfile

Keep one image and copy both executables:
- `/app/runner.py` (SQL)
- `/app/runner_python.py` (Python)

Default `ENTRYPOINT` can remain SQL for backward compatibility.
Agent-server overrides entrypoint for Python runs:

```bash
docker run --entrypoint python3 <image> /app/runner_python.py
```

## 5.2 Shared Utilities

Create shared module (e.g., `runner/common.py`) for:
- request parsing/validation primitives
- CSV path sanitization
- table-name sanitization
- standard response helpers
- timeout utilities

---

## 6) Python Execution Model

## 6.1 Data Exposure

At runtime, load CSVs into pandas DataFrames and expose as:

- `dfs`: dict keyed by table name (`{"tickets": DataFrame, ...}`)
- convenience globals per table name (`tickets`, `orders`, etc.)

No direct file paths are exposed to user code.

## 6.2 Required Output Protocol

User code must set exactly one of:
- `result_df` (pandas DataFrame)
- `result_rows` (+ optional `result_columns`)
- `result` (scalar/dict/list, normalized by adapter)

Adapter converts to tabular response and enforces:
- `max_rows`
- `max_output_bytes`

## 6.3 Execution Namespace

Provide minimal globals:
- Allowed: `pd`, `np`, `dfs`, table aliases, safe builtins subset
- Block: `open`, `exec`, `eval`, `compile`, `__import__`, `input`

---

## 7) Security Guardrails

## 7.1 AST Policy Validation (Pre-execution)

Parse `python_code` and reject disallowed nodes/patterns:
- imports outside allowlist
- attribute access to blocked modules
- dynamic code execution (`eval`, `exec`)
- filesystem/process/network APIs

### Allowlist (initial)
- modules: `pandas`, `numpy`, `math`, `statistics`, `re`, `datetime`
- optionally `duckdb` (read-only in-memory usage only)

### Blocklist (initial)
- modules: `os`, `sys`, `subprocess`, `socket`, `pathlib`, `shutil`, `ctypes`, `importlib`
- functions: `open`, `exec`, `eval`, `compile`, `__import__`

## 7.2 Runtime Sandbox

Continue relying on container boundary as primary control:
- no network
- read-only root FS
- non-root user
- CPU/memory/pid/time limits

## 7.3 Output/Data Exfil Controls

- row cap (`max_rows`)
- byte cap (`max_output_bytes`)
- truncate stdout/stderr
- optional heuristic checks for massive schema dumps (future)

---

## 8) Error Taxonomy

Reuse existing errors where possible; add Python-specific types:

- `VALIDATION_ERROR`
- `PYTHON_POLICY_VIOLATION`
- `PYTHON_EXECUTION_ERROR`
- `RUNNER_TIMEOUT`
- `RUNNER_RESOURCE_EXCEEDED`
- `RUNNER_INTERNAL_ERROR`

All errors must include:
- `type`
- `message`

---

## 9) Agent-Server Changes

## 9.1 New Tool

Add `execute_python(dataset_id, python_code)`.

Execution flow:
1. validate dataset
2. python policy validation (agent-side optional pre-check)
3. invoke runner with Python entrypoint
4. normalize result
5. persist run capsule

## 9.2 Chat Policy

Default behavior remains plan/SQL.
Python mode is used only when:
- user explicitly requests Python, or
- SQL path cannot satisfy required transformation (future heuristic)

## 9.3 Run Capsule

Add fields:
- `query_type`
- `python_code`
- `python_policy_report` (optional)

---

## 10) UI Requirements

Minimal additions:
- show `query_type` in details panel
- show Python code when executed
- preserve existing streaming statuses (`planning`, `validating`, `executing`, `result`, `done`)

No major UI redesign required.

---

## 11) TDD Plan

Phase A: Runner core
1. Failing tests for Python request validation.
2. Failing tests for AST policy allow/deny cases.
3. Failing tests for output normalization (`result_df`, scalar, list).
4. Implement `runner_python.py` until passing.

Phase B: Integration
1. Container integration test: simple pandas aggregation succeeds.
2. Integration test: blocked import (`os`) rejected.
3. Integration test: timeout classification for infinite loop.
4. Integration test: output row/byte caps enforced.

Phase C: Agent-server
1. Failing tests for `execute_python` path.
2. Failing tests for `/chat` explicit Python request.
3. Failing tests for capsule persistence of `python_code`.
4. Implement until passing.

Phase D: Security
1. Red-team fixtures for subprocess/network/file access attempts.
2. Validate all are rejected before execution.

---

## 12) Deployment and Ops

- No extra image required.
- Existing deploy pipeline remains mostly unchanged.
- Runtime selector in agent-server decides entrypoint per run.
- Keep feature flag for controlled rollout:
  - `ENABLE_PYTHON_EXECUTION=false` by default.

---

## 13) Acceptance Criteria

1. Python query executes in sandbox and returns tabular JSON.
2. SQL path remains fully backward compatible.
3. Blocked Python patterns are rejected deterministically.
4. Timeout/resource limits apply equally to Python runs.
5. Run capsule records Python execution metadata.
6. E2E tests pass for one golden Python query per dataset.

---

## 14) Recommended First Increment

Implement only these first:
- `runner_python.py` with AST policy + pandas DataFrame output.
- agent-server direct Python tool call (no automatic NL-to-Python planning).
- one explicit UI test command format, e.g.:
  - `PYTHON: result_df = tickets.groupby('priority').size().reset_index(name='n')`

Then iterate toward natural-language Python planning in a second pass.
