# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project structure and directory organization
- Project documentation (README.md, CLAUDE.md, CONTRIBUTING.md)
- Development tooling (Makefile with 30+ commands)
- Git repository initialization
- Comprehensive TODO.md with phased implementation plan
- PRD documents (core and deployment)
- Use case specifications for 3 datasets with 18 golden queries
- Decision log (DECISIONS.md) documenting architectural choices
- .gitignore for Python, Node, and common IDE files

**Datasets (Phase 1.1)**:
- Data generation scripts for 3 datasets (deterministic, seeded random)
- E-commerce dataset: 13,526 rows (orders, items, inventory)
- Support tickets dataset: 6,417 rows (ticket lifecycle data)
- IoT sensors dataset: 49,950 rows (time-series with anomalies)
- Dataset registry (registry.json) with schemas, prompts, version hashes
- Dataset validation script with quality checks
- Comprehensive dataset documentation (README.md, GENERATION_REPORT.md)

**QueryPlan DSL (Phase 1.2)**:
- Pydantic models for structured query representation
- QueryPlan, Filter, Aggregation, SelectColumn, OrderBy models
- 11 filter operators (comparison, list, pattern, NULL checks)
- 6 aggregation functions (count, sum, avg, min, max, count_distinct)
- SQL compiler with deterministic QueryPlan → SQL compilation
- DuckDB-compatible SQL generation
- SQL injection prevention (identifier validation, value escaping)
- Data exfiltration heuristic for suspicious queries
- QueryRequest envelope for extensible query types (plan, sql, python, json_query)
- Comprehensive test suite: 66 tests (100% pass rate)
- Demo script with 7 usage examples
- Full documentation (agent-server/README.md, QUERYPLAN_DSL_SPEC.md)

**Runner (Phase 1.4)**:
- Sandboxed DuckDB runner implementation (`runner/runner.py`)
- Hardened runner Docker image (`runner/Dockerfile`)
- Runner container integration tests (7 tests)
- Make targets for runner validation: `build-runner-test`, `test-runner`
- Python sandbox execution entrypoint in same image (`runner/runner_python.py`)
- Runner python dependencies (`pandas`, `numpy`) and policy enforcement path
- Shared runner utilities module (`runner/common.py`) for path/table sanitization and response model
- Network-egress integration test for runner container hardening (`--network none`)

**Single-File Agent Server (Phase 1.5, minimal first iteration)**:
- Single-file FastAPI implementation (`agent-server/app/main.py`)
- API endpoints: `/healthz`, `/datasets`, `/datasets/{id}/schema`, `/chat`, `/chat/stream`, `/runs/{run_id}`
- Static UI served from same FastAPI app (`GET /`) with streaming chat consumption
- SQLite run capsule persistence and retrieval
- Optional `.env` loading support from repo root and cwd
- OpenAI provider support (`OPENAI_API_KEY`, `OPENAI_MODEL`, `LLM_PROVIDER`)
- Integration test suite for single-file server (`tests/integration/test_agent_server_singlefile.py`)
- Agent server run targets in Makefile: `run-agent`, `run-agent-dev`, `test-agent-server`
- Server specification doc: `AGENT_SERVER_SPECIFICATION.md`
- Python execution design spec: `PYTHON_EXECUTION_SPEC.md` (same runner image, separate entrypoint plan)
- Explicit python chat mode (`PYTHON: ...`) wired to runner python entrypoint
- Implicit python-intent routing for prompts like "use pandas ..." with LLM generation + heuristic fallback
- Executor layer modules (`agent-server/app/executors`) with `Executor` interface and `DockerExecutor`
- Direct run APIs (`POST /runs`, `GET /runs/{run_id}/status`)
- DockerExecutor integration tests (`tests/integration/test_docker_executor_integration.py`)
- Expanded python policy/security coverage (subprocess/network/file import/call rejection tests)

### Changed
- Updated CLAUDE.md with dataset generation and testing guidance
- Updated README.md with current project status
- Updated TODO.md with completed tasks (Phase 0.1, 1.1, 1.2)
- Updated runner timeout classification to return `RUNNER_TIMEOUT` consistently
- Updated support/sensors dataset generation for data validity edge cases
- Updated implementation/status docs with runner usage and test workflow
- Updated docs for single-file server usage, static UI, streaming endpoint, and env placement
- Updated root `.env.example` to include provider/runtime configuration for the single-file server
- Updated Makefile to enforce `agent-server/.venv` for server and Python test targets (`agent-venv` bootstrap)
- Updated TODO/docs status to include sequenced Phase 1 Python-execution implementation checklist
- Updated docs with python runner usage, env vars, and revised test counts
- Updated TODO/implementation docs to mark Phase 0 complete and Phase 1 complete except stretch AST parser
- Updated `make test-runner` to always use `agent-server/.venv` and include DockerExecutor integration tests

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Support tickets edge cases where `resolved_at < created_at`
- Sensors edge cases with out-of-range humidity values
- Runner image base now uses `python:3.11-slim` for DuckDB wheel compatibility in local test builds
- LLM structured output compatibility issue where dict output caused attribute errors in chat flow
- SQL policy false positive where `created_at` matched blocked token `create`
- Dataset-qualified SQL table references (e.g., `support.tickets`) now normalize to runner-loaded table names
- Agent server now supports explicit python execution mode and feature-flag rejection path
- DockerExecutor now handles docker SDK transport incompatibilities with CLI health-check fallback

### Security
- SQL injection prevention in QueryPlan compiler
- Data exfiltration detection heuristic
- Dataset version hashing for integrity
- Runner CSV path confinement to `/data` and strict table-name sanitization

---

## [0.1.0] - 2026-02-02

### Added
- Initial project bootstrap
- Documentation framework
- Development environment setup

---

## Release Notes Format

Each version should include:
- Version number [X.Y.Z]
- Release date (YYYY-MM-DD)
- Changes grouped by category:
  - Added: New features
  - Changed: Changes in existing functionality
  - Deprecated: Soon-to-be removed features
  - Removed: Removed features
  - Fixed: Bug fixes
  - Security: Security improvements

## Version Numbering

- **Major (X.0.0)**: Breaking changes, major features
- **Minor (0.X.0)**: New features, backwards compatible
- **Patch (0.0.X)**: Bug fixes, minor improvements
