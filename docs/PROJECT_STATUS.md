# Project Status Report

**Last Updated**: 2026-02-03  
**Current Phase**: Phase 2 in progress (K8s/Helm execution path active)

## Overall Progress

```text
Phase 0: Bootstrap & Planning         ████████████████████ 100% ✅
Phase 1: Foundations + Minimal UX     ████████████████████ 100% ✅
Phase 2: Production Shape             ████████░░░░░░░░░░░░  40% 🚧
Phase 3: Polish & Deployment          ░░░░░░░░░░░░░░░░░░░░   0% ⏭️
```

## Completed Components ✅

### Data + Query Foundation
- ✅ Deterministic dataset generation + registry
- ✅ QueryPlan DSL models and deterministic compiler
- ✅ `agent-server/demo_query_plan.py` DSL demonstrations

### Runner (Sandboxed SQL + Python)
- ✅ Hardened DuckDB runner (`runner/runner.py`, `runner/Dockerfile`)
- ✅ CSV load/path/table-name hardening
- ✅ Timeout classification (`RUNNER_TIMEOUT`)
- ✅ Containerized integration tests (`tests/integration/test_runner_container.py`)
- ✅ Python runner entrypoint in same image (`runner/runner_python.py`)
- ✅ Python policy guardrails (AST allow/block checks + blocked builtins)
- ✅ Shared runner utilities module (`runner/common.py`)

### Single-File Agent Server + UI
- ✅ `agent-server/app/main.py` FastAPI server
- ✅ Endpoints: health, datasets, schema, chat, stream, runs
- ✅ Run capsule persistence (SQLite)
- ✅ Minimal static UI served from same app
- ✅ Streaming wired through `POST /chat/stream`
- ✅ Integration tests (`tests/integration/test_agent_server_singlefile.py`)
- ✅ LLM-output hardening:
  - dict response coercion for structured output compatibility
  - non-executable draft handling + SQL rescue pass
- ✅ SQL policy hardening:
  - denylist token word-boundary checks (fixes `created_at` false positive)
  - dataset-qualified table normalization for runner compatibility
- ✅ Explicit Python chat mode (`PYTHON: ...`) wired to python runner entrypoint
- ✅ `/runs` submission API + `/runs/{run_id}/status`
- ✅ Stateful chat via `thread_id` + persisted thread message history
- ✅ Result-grounded assistant summaries (scalar inline answer, complex result references)

### Executor Layer
- ✅ Executor interface + DockerExecutor module
- ✅ Docker SDK path with CLI fallback when SDK transport is unavailable
- ✅ DockerExecutor integration tests (SQL and Python modes)
- ✅ Configurable sandbox provider flag (`SANDBOX_PROVIDER`)
- ✅ MicroSandbox executor implementation and provider wiring (live E2E validated)
- ✅ Live MicroSandbox integration coverage (`RUN_MICROSANDBOX_TESTS=1`)
- ✅ Kubernetes Job executor path (`SANDBOX_PROVIDER=k8s`) with Helm/RBAC wiring
- ✅ Local kind + remote VPS deployment runbook (`docs/runbooks/K8S_HELM_DOCKER_RUNBOOK.md`)
- ✅ Profile-based Helm context guide (`k8s` vs `microsandbox`) for Kubernetes deployment (`docs/runbooks/K8S_HELM_PROFILE_CONTEXTS.md`)

## In Progress 🚧

- 🚧 Stretch: SQL AST parser for stricter validation
- 🚧 UI polish and richer execution transparency UX

## Pending Components ⏭️

- Helm deployment/runtime hardening
- Expanded security/red-team suite
- Production observability/reliability features

## Metrics

### Tests (validated today)

```text
Unit tests                               104 tests ✅
Security tests                             6 tests ✅
Agent-server integration                  25 tests ✅
Runner + DockerExecutor integration       14 tests ✅
MicroSandbox executor/provider             6 tests ✅
-----------------------------------------------------
TOTAL                                    155 tests ✅
```

### Datasets

```text
ecommerce     13,526 rows    3 files
support        6,417 rows    1 file
sensors       49,950 rows    1 file
--------------------------------------
TOTAL         69,893 rows    5 files
```

## Runner Arrangement (Confirmed)

- QueryPlan DSL remains upstream in agent-server.
- Runner SQL path receives compiled SQL and executes inside sandbox.
- Runner Python path executes explicit `PYTHON:` code in sandbox via separate entrypoint.

## Next Milestones

1. Tighten SQL policy validator and rejection messaging.
2. Add more end-to-end tests per use-case prompt.
3. Improve UI details panel and run inspection flow.
4. Add unit/security tests for python policy and output guards.
5. Begin production-shape execution path (K8s + Helm).
