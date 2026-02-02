# Project Status Report

**Last Updated**: 2026-02-02  
**Current Phase**: Phase 1 - Foundations (In Progress)

## Overall Progress

```
Phase 0: Bootstrap & Planning         ████████████████████ 100% ✅
Phase 1: Foundations                  ████████████░░░░░░░░  60% 🚧
Phase 2: Production Shape             ░░░░░░░░░░░░░░░░░░░░   0% ⏭️
Phase 3: Polish & Deployment          ░░░░░░░░░░░░░░░░░░░░   0% ⏭️
```

## Completed Components ✅

### Phase 0: Project Bootstrap
- ✅ Project structure and baseline docs
- ✅ PRD and implementation planning docs
- ✅ Dataset/use-case documentation and planning artifacts

### Phase 1.1: Dataset Generation
- ✅ Deterministic generators for ecommerce/support/sensors datasets
- ✅ `datasets/registry.json` with metadata and version hashes
- ✅ Dataset validation script
- ✅ Data quality fixes applied (timestamp consistency, humidity bounds)

### Phase 1.2: QueryPlan DSL + Compiler
- ✅ QueryPlan Pydantic models and validation
- ✅ Deterministic QueryPlan → SQL compiler
- ✅ Unit test suite for DSL/compiler
- ✅ `agent-server/demo_query_plan.py` for DSL demonstrations

### Phase 1.4: Runner (SQL Mode)
- ✅ Sandboxed DuckDB runner implementation (`runner/runner.py`)
- ✅ Hardened runner Docker image (`runner/Dockerfile`)
- ✅ CSV loading hardening:
  - absolute-path enforcement
  - `/data` root confinement
  - safe table-name validation
  - bound parameter use for CSV file paths
- ✅ Correct timeout classification (`RUNNER_TIMEOUT`)
- ✅ Integration tests for runner container behavior

## In Progress 🚧

### Phase 1.3: SQL Validation
- 🚧 SQL policy validator for raw SQL execution path
- 🚧 Security/red-team fixtures beyond runner-level checks

## Pending Components ⏭️

### Phase 1.5+: Orchestration and Product Surface
- Docker/K8s executors in agent-server
- FastAPI endpoints and agent orchestration
- Run capsule persistence
- UI integration
- Helm chart and Kubernetes Job runtime

## Metrics

### Tests
```
tests/unit/test_query_plan.py            36 tests ✅
tests/unit/test_compiler.py              30 tests ✅
tests/integration/test_runner_container.py 7 tests ✅
--------------------------------------------------------
TOTAL                                    73 tests ✅
```

### Datasets
```
ecommerce     13,526 rows    3 files
support        6,417 rows    1 file
sensors       49,950 rows    1 file
--------------------------------------
TOTAL         69,893 rows    5 files
```

## Runner Usage (Current)

- Build runner test image: `make build-runner-test`
- Run runner integration tests: `make test-runner`
- Validate datasets before test runs: `python3 scripts/validate_datasets.py`

## Known Gaps / Risks

- No end-to-end agent-server → executor → runner flow yet
- No deployed UI path yet
- No Kubernetes execution path validated yet

## Next Milestones

1. Implement SQL policy validator for raw SQL path.
2. Add DockerExecutor in agent-server and wire runner calls.
3. Expose execution via API endpoint(s) and start E2E flow tests.
4. Implement K8sJobExecutor + Helm chart for prod-like environment.

## Summary

The runner is now implemented, hardened, and integration-tested. The project has a strong data + DSL + execution core and is ready for orchestration-layer implementation (executors, APIs, UI, and Kubernetes deployment path).
