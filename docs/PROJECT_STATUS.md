# Project Status Report

**Last Updated**: 2026-02-02  
**Current Phase**: Phase 1 - Foundations + Minimal Product Surface

## Overall Progress

```text
Phase 0: Bootstrap & Planning         ████████████████████ 100% ✅
Phase 1: Foundations + Minimal UX     ████████████████░░░░  80% 🚧
Phase 2: Production Shape             ░░░░░░░░░░░░░░░░░░░░   0% ⏭️
Phase 3: Polish & Deployment          ░░░░░░░░░░░░░░░░░░░░   0% ⏭️
```

## Completed Components ✅

### Data + Query Foundation
- ✅ Deterministic dataset generation + registry
- ✅ QueryPlan DSL models and deterministic compiler
- ✅ `agent-server/demo_query_plan.py` DSL demonstrations

### Runner (Sandboxed SQL)
- ✅ Hardened DuckDB runner (`runner/runner.py`, `runner/Dockerfile`)
- ✅ CSV load/path/table-name hardening
- ✅ Timeout classification (`RUNNER_TIMEOUT`)
- ✅ Containerized integration tests (`tests/integration/test_runner_container.py`)

### Single-File Agent Server + UI
- ✅ `agent-server/app/main.py` FastAPI server
- ✅ Endpoints: health, datasets, schema, chat, stream, runs
- ✅ Run capsule persistence (SQLite)
- ✅ Minimal static UI served from same app
- ✅ Streaming wired through `POST /chat/stream`
- ✅ Integration tests (`tests/integration/test_agent_server_singlefile.py`)

## In Progress 🚧

- 🚧 Stronger SQL policy coverage and edge-case handling
- 🚧 Additional end-to-end scenarios across all datasets
- 🚧 UI polish and richer execution transparency UX

## Pending Components ⏭️

- Kubernetes Job executor path
- Helm deployment/runtime hardening
- Expanded security/red-team suite
- Production observability/reliability features

## Metrics

### Tests (validated today)

```text
tests/unit/test_query_plan.py               36 tests ✅
tests/unit/test_compiler.py                 30 tests ✅
tests/integration/test_agent_server_singlefile.py  7 tests ✅
tests/integration/test_runner_container.py   7 tests ✅
-----------------------------------------------------
TOTAL                                       80 tests ✅
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
- Runner receives and executes SQL only.
- This is the intended architecture for current scope.

## Next Milestones

1. Tighten SQL policy validator and rejection messaging.
2. Add more end-to-end tests per use-case prompt.
3. Improve UI details panel and run inspection flow.
4. Begin production-shape execution path (K8s + Helm).
