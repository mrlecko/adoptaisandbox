# Feature: MicroSandbox as Configurable Sandbox Provider

## Goal

Add MicroSandbox as an execution backend option, while keeping Docker support.

- `SANDBOX_PROVIDER=docker|microsandbox`
- Same request/response contract to the agent server, regardless of provider
- SQL and Python execution support in both modes

## Estimated LoE

- MVP: **5-7 engineering days**
- Production hardening: **+3-5 days**

---

## Implementation Checklist

## 0) Preflight + Design Lock

- [~] Confirm MicroSandbox host/runtime prerequisites in target environments (dev + prod-like)
- [~] Confirm auth model (`MSB_API_KEY`) and endpoint config for all environments
- [~] Lock contract parity requirements with current Docker executor:
  - [x] Timeout semantics
  - [x] Error type mapping
  - [x] Output truncation behavior
  - [~] Data mount behavior

## 1) Configuration + Settings

- [x] Add new env vars to `.env.example`:
  - [x] `SANDBOX_PROVIDER=docker`
  - [x] `MSB_SERVER_URL=...`
  - [x] `MSB_API_KEY=...`
  - [x] `MSB_NAMESPACE=...`
  - [x] `MSB_CPUS=...`
  - [x] `MSB_MEMORY_MB=...`
- [x] Update `Settings` model in `agent-server/app/main.py` to include MicroSandbox config
- [x] Validate config on startup (clear startup error if provider is microsandbox but config is missing)

## 2) Executor Abstraction Hardening

- [x] Verify/adjust executor interface in `agent-server/app/executors/base.py` for provider parity
- [x] Ensure sync behavior is consistent for both providers (`submit_run`, `get_status`, `get_result`, `cleanup`)
- [x] Add provider-neutral status/result normalization helpers if needed

## 3) Implement `MicroSandboxExecutor`

- [x] Add `agent-server/app/executors/microsandbox_executor.py`
- [x] Implement sandbox lifecycle for each run:
  - [x] Create/start sandbox
  - [x] Inject runner payload
  - [x] Execute SQL path
  - [x] Execute Python path
  - [x] Collect stdout/stderr
  - [x] Parse and normalize runner JSON response
  - [x] Cleanup sandbox resources
- [x] Implement robust error handling:
  - [x] Sandbox create/start failures
  - [x] Execution timeout
  - [x] Non-JSON response
  - [x] Transport/retryable failures

## 4) Provider Selection Wiring

- [x] Add executor factory (new module or in `executors/__init__.py`)
- [x] Select executor by `SANDBOX_PROVIDER`
- [x] Keep Docker as default
- [x] Preserve current behavior when `SANDBOX_PROVIDER` is unset

## 5) Request/Response Contract Parity

- [x] Keep same runner payload fields across providers:
  - [x] `dataset_id`, `files`, `query_type`, `sql|python_code`, `timeout_seconds`, `max_rows`, `max_output_bytes`
- [x] Keep same response fields across providers:
  - [x] `status`, `columns`, `rows`, `row_count`, `exec_time_ms`, `stdout_trunc`, `stderr_trunc`, `error`
- [x] Ensure SQL policy and Python policy are unchanged at agent layer

## 6) Tests (TDD)

### Unit
- [x] Add `tests/unit/test_microsandbox_executor.py`
  - [x] Happy path SQL result mapping
  - [x] Happy path Python result mapping
  - [x] Timeout mapping
  - [x] Invalid JSON mapping
  - [x] Cleanup behavior

### Integration
- [x] Add `tests/integration/test_microsandbox_executor_integration.py`
  - [x] SQL query end-to-end
  - [x] Python query end-to-end
  - [x] Policy rejection path
  - [x] Timeout path
- [~] Add provider matrix smoke coverage:
  - [x] `docker` provider run
  - [~] `microsandbox` provider run (live run behind `RUN_MICROSANDBOX_TESTS=1`)

### Regression
- [x] Ensure existing tests pass unchanged with Docker default
- [x] Add at least one chat-flow integration test with `SANDBOX_PROVIDER=microsandbox`

## 7) Makefile + Developer Workflow

- [x] Add Make target(s):
  - [x] `make test-microsandbox` (provider-specific tests + opt-in live integration)
  - [x] `make run-agent-microsandbox` (env-configured run helper)
- [x] Ensure venv usage remains enforced (`agent-server/.venv`)

## 8) Docs

- [x] Update `README.md` with provider selection and env setup
- [x] Update `docs/QUICK_START.md` with Docker vs MicroSandbox paths
- [x] Update `docs/PROJECT_STATUS.md` once merged
- [x] Update `CHANGELOG.md`
- [x] Add troubleshooting section for common MicroSandbox startup/auth issues

## 9) Rollout + Safety

- [x] Keep Docker as default provider
- [x] Gate MicroSandbox with explicit config
- [x] Add fallback guidance:
  - [x] If MicroSandbox init fails, fail fast with actionable error
  - [x] Do not silently switch providers
- [x] Add metrics/log fields for provider used per run

---

## Acceptance Criteria

- [x] Agent runs SQL queries successfully with `SANDBOX_PROVIDER=docker`
- [~] Agent runs SQL queries successfully with `SANDBOX_PROVIDER=microsandbox` (live env required)
- [~] Agent runs Python queries successfully with both providers (live env required for microsandbox)
- [x] Same API response contract for both providers
- [x] Timeouts and policy failures are mapped consistently
- [x] Existing regression suite passes
- [~] Provider-specific integration tests pass (live env required)

---

## Out of Scope (for this feature)

- Implementing Redis/Postgres message storage providers
- Replacing existing runner protocol
- Kubernetes-specific MicroSandbox orchestration changes (unless required for basic connectivity)
