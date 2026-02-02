# CSV Analyst Chat - Master TODO List

**Status Legend:**
- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked

---

## Phase 0: Bootstrap & Planning (Day 0)

### P0.1 Project Structure
- [x] Create initial PRD documents (Core + Deployment)
- [x] Review and finalize PRDs
- [x] Create master TODO.md (this file)
- [x] Set up project directory structure
- [x] Initialize Git repository
- [x] Create .gitignore (secrets, .env, __pycache__, etc.)
- [x] Create initial README.md skeleton
- [x] Create CLAUDE.md for cross-session context
- [x] Create CONTRIBUTING.md
- [x] Create use case specifications (3 datasets)

### P0.2 Tech Stack Validation
- [ ] Verify LangChain Agent UI starter compatibility
- [ ] Test LangChain agent graph basics locally
- [ ] Validate DuckDB for CSV querying
- [ ] Confirm Docker SDK for Python (local runner)
- [ ] Confirm Kubernetes Python client (K8s runner)

### P0.3 Environment Setup
- [ ] Define directory structure (/datasets, /agent-server, /runner, /ui, /helm, /tests)
- [ ] Create pyproject.toml / requirements.txt for agent server
- [ ] Create Dockerfile stubs (UI, agent-server, runner)
- [ ] Create docker-compose.yml stub
- [ ] Create Makefile with targets (dev, smoke, clean, k8s-up, helm-install)

**PRD Mapping:** Sections 0, 17, Deployment-B, Deployment-F

---

## Phase 1: Foundations (Days 1-2)

### P1.1 Dataset Generation & Registry (FR-D1, FR-D2, FR-D3)
- [x] Create `/datasets` directory structure
- [x] Design dataset metadata schema (datasets/registry.json)
  - Fields: id, description, files, schema, version_hash, prompts
- [x] Generate Dataset A: Ecommerce
  - [x] orders.csv (order_id, customer_id, order_date, total, status, returned)
  - [x] order_items.csv (item_id, order_id, product_id, category, quantity, price, discount)
  - [x] inventory.csv (product_id, name, category, stock)
  - [x] 6 demo prompts
- [x] Generate Dataset B: Support Tickets
  - [x] tickets.csv (ticket_id, created_at, resolved_at, category, priority, csat_score, sla_met)
  - [x] 6 demo prompts
- [x] Generate Dataset C: Sensor/Time Series
  - [x] sensors.csv (sensor_id, timestamp, location, temp, humidity, anomaly_flag)
  - [x] 6 demo prompts
- [x] Implement dataset version hashing (SHA256 of CSVs)
- [ ] Create dataset loader utility
- [ ] Write unit tests for dataset registry loader

**PRD Mapping:** Section 12, FR-D1-D3

### P1.2 Query Plan JSON DSL (FR-Q1, FR-Q2, FR-Q3)
- [ ] Define QueryPlan JSON schema (Pydantic models)
  - [ ] dataset_id, table, select, filters, group_by, order_by, limit, notes
  - [ ] Filter operators: =, !=, <, <=, >, >=, in, between, contains, startswith, endswith
  - [ ] Aggregations: sum, avg, min, max, count, count_distinct
- [ ] Implement schema validator (Pydantic)
- [ ] Implement QueryPlan → SQL compiler
  - [ ] Handle column selection
  - [ ] Handle filters (including LIKE patterns for contains/startswith/endswith)
  - [ ] Handle GROUP BY
  - [ ] Handle aggregations
  - [ ] Handle ORDER BY
  - [ ] Enforce LIMIT (default 200 if missing)
  - [ ] Deterministic compilation
- [ ] Write unit tests for compiler (good/bad plans)
- [ ] Write unit tests for edge cases (missing limit, too many columns)

**PRD Mapping:** Section 9, FR-Q1-Q3

### P1.3 SQL Validation (FR-SQL1, FR-SQL2, FR-SQL3)
- [ ] Implement SQL policy validator
  - [ ] Denylist: DROP, DELETE, INSERT, UPDATE, CREATE, ALTER, ATTACH, INSTALL, LOAD, PRAGMA, CALL, COPY, EXPORT
  - [ ] Allowlist mode: SELECT, WITH, common expressions
  - [ ] Case-insensitive matching
- [ ] (Stretch) Implement SQL AST parser for stricter validation
- [ ] Write unit tests for SQL validator (allowed/forbidden queries)
- [ ] Write "red team" test fixtures (injection attempts)

**PRD Mapping:** FR-SQL1-SQL3, Section 15.3

### P1.4 Runner (SQL Mode) (FR-X1-X4, Section 10)
- [ ] Create `/runner` directory
- [ ] Create runner Dockerfile
  - [ ] Base image: Python 3.11-slim
  - [ ] Install DuckDB
  - [ ] Copy runner script
  - [ ] Non-root user (UID 1000)
  - [ ] Read-only root filesystem (use /tmp for DuckDB working dir)
- [ ] Implement runner.py
  - [ ] Read RunnerRequest JSON from stdin
  - [ ] Load CSVs into DuckDB tables
  - [ ] Execute SQL with timeout
  - [ ] Return RunnerResponse JSON to stdout
    - Fields: status, columns, rows, row_count, exec_time_ms, stdout_trunc, stderr_trunc, error
  - [ ] Handle errors gracefully
  - [ ] Respect max_rows limit
- [ ] Test runner locally (docker run with test inputs)
- [ ] Write unit tests for runner (mocked DuckDB)

**PRD Mapping:** Section 10, FR-X1-X4

### P1.5 Docker Executor (Local Mode) (Deployment-B)
- [ ] Create `/agent-server/executors` module
- [ ] Implement Executor interface (abstract class)
  - Methods: submit_run(), get_status(), get_result(), cleanup()
- [ ] Implement DockerExecutor
  - [ ] Use Docker SDK for Python
  - [ ] Create container with:
    - `--network none`
    - `--read-only`
    - `--pids-limit 64`
    - `--memory 512m --cpus 0.5`
    - `--tmpfs /tmp:rw,noexec,nosuid,size=64m`
    - Mount datasets read-only at /data
  - [ ] Pass RunnerRequest JSON via stdin
  - [ ] Collect RunnerResponse JSON from stdout
  - [ ] Handle timeouts (kill container)
  - [ ] Cleanup containers after completion
- [ ] Write integration tests for DockerExecutor

**PRD Mapping:** Deployment-B, FR-X2-X4

### P1.6 Agent Server Core (FR-A1-A3, Section 7, 13)
- [ ] Create `/agent-server` directory
- [ ] Set up FastAPI application
- [ ] Implement dataset endpoints
  - [ ] GET /datasets (FR metadata)
  - [ ] GET /datasets/{id}/schema
- [ ] Implement LangChain agent graph
  - [ ] Define agent tools:
    - list_datasets()
    - get_dataset_schema(dataset_id)
    - execute_query_plan(dataset_id, plan_json)
    - execute_sql(dataset_id, sql)
    - get_run_status(run_id)
  - [ ] System prompt enforcing JSON plan default, SQL optional
  - [ ] Structured output for QueryPlan
- [ ] Implement /chat endpoint
  - [ ] Accept: dataset_id, thread_id (optional), message
  - [ ] Call agent graph
  - [ ] Validate plan/SQL
  - [ ] Submit to executor
  - [ ] Return assistant message + run status + result
- [ ] Implement /runs endpoints
  - [ ] POST /runs (submit plan/SQL)
  - [ ] GET /runs/{run_id} (fetch capsule)
- [ ] Add health endpoint (/healthz)
- [ ] Add structured logging (JSON logs)

**PRD Mapping:** Section 7, 13, FR-A1-A3

### P1.7 Run Capsule Storage (FR-R1-R3)
- [ ] Design run_capsules table schema (SQLite)
  - Fields: run_id, timestamp, dataset_id, dataset_version_hash, question, plan_json, compiled_sql, runner_mode, resource_limits, result_preview, stats, stdout, stderr, status, error
- [ ] Implement capsule persistence layer
- [ ] Implement capsule retrieval by run_id
- [ ] Add indexing for efficient lookups
- [ ] Write unit tests for capsule CRUD

**PRD Mapping:** FR-R1-R3, Section 14.2

### P1.8 UI Integration (FR-UI1-UI3)
- [ ] Clone/set up LangChain Agent UI starter
- [ ] Configure UI to talk to agent server
- [ ] Add dataset selection dropdown
  - Fetch datasets from GET /datasets
  - Display suggested prompts per dataset
- [ ] Add chat message input
- [ ] Display assistant responses (streaming if supported)
- [ ] Add "Show details" panel
  - Query plan JSON (formatted)
  - Compiled SQL (formatted)
  - Execution stats/logs
  - Result table preview
- [ ] Add run status indicators (Pending, Running, Succeeded, Failed, Rejected)
- [ ] Test end-to-end flow locally

**PRD Mapping:** FR-UI1-UI3

**Deliverable:** Local dev environment works end-to-end via `docker compose up`

---

## Phase 2: Production Shape (Days 3-4)

### P2.1 Kubernetes Job Executor (FR-X4, Deployment-C)
- [ ] Implement K8sJobExecutor
  - [ ] Use Kubernetes Python client
  - [ ] Create Job spec with:
    - Runner image
    - RunnerRequest JSON via environment variable
    - Dataset access (baked into image for MVP)
    - Security context (runAsNonRoot, readOnlyRootFilesystem, drop ALL caps, no privilege escalation)
    - Resource limits (cpu, memory from config)
  - [ ] Submit Job to namespace
  - [ ] Poll Job status (Pending, Running, Succeeded, Failed)
  - [ ] Fetch Pod logs for RunnerResponse JSON
  - [ ] Cleanup completed Jobs (with retention policy)
- [ ] Test K8sJobExecutor with kind/k3d cluster
- [ ] Write integration tests

**PRD Mapping:** Section 11, FR-X4, Deployment-C

### P2.2 Helm Chart (Deployment-C)
- [ ] Create `/helm/csv-analyst-chat` directory
- [ ] Create Chart.yaml (name, version, description)
- [ ] Create values.yaml
  - Image repository, tags, pullPolicy
  - Ingress host, TLS on/off
  - Execution mode (docker/k8s)
  - Runner config (timeout, max_rows, resource limits)
  - Agent server replicas
  - UI replicas
- [ ] Create templates/
  - [ ] deployment-ui.yaml
  - [ ] deployment-agent-server.yaml
  - [ ] service-ui.yaml
  - [ ] service-agent-server.yaml
  - [ ] ingress.yaml (with host, TLS config)
  - [ ] serviceaccount.yaml (for agent server)
  - [ ] role.yaml (Jobs: create/get/list/watch; Pods: get/list/watch; Pod logs: get)
  - [ ] rolebinding.yaml
  - [ ] networkpolicy.yaml (deny egress for runner pods)
  - [ ] configmap-datasets.yaml (optional, for dataset metadata)
- [ ] Lint Helm chart (`helm lint`)
- [ ] Test Helm install on kind cluster
- [ ] Write smoke test for K8s mode (`make k8s-smoke`)

**PRD Mapping:** Deployment-C, Section 11, NFR-SEC1

### P2.3 Security Hardening (NFR-SEC1-SEC3)
- [ ] Verify runner security context in K8s
  - [ ] runAsNonRoot: true
  - [ ] allowPrivilegeEscalation: false
  - [ ] readOnlyRootFilesystem: true
  - [ ] capabilities.drop: ["ALL"]
- [ ] Verify NetworkPolicy denies egress for runner pods
- [ ] Implement output row limit (200 default)
- [ ] Implement output byte limit for stdout/stderr (64KB)
- [ ] Implement data exfil heuristic (reject queries missing limit + selecting many columns + no aggregation)
- [ ] Add system prompt safeguards against prompt injection
- [ ] Write security test fixtures
  - [ ] Prompt injection attempts
  - [ ] SQL injection attempts
  - [ ] Data exfil attempts
  - [ ] Resource exhaustion attempts
- [ ] Document security model in README

**PRD Mapping:** NFR-SEC1-SEC3, Section 15.3

### P2.4 Reliability & Error Handling (NFR-REL1-REL2)
- [ ] Implement timeout enforcement (runner killed after timeout)
- [ ] Implement graceful error handling for:
  - Invalid plan → VALIDATION_ERROR
  - Invalid SQL → SQL_POLICY_VIOLATION
  - Runner failure → RUNNER_INTERNAL_ERROR
  - Timeout → RUNNER_TIMEOUT
  - Resource exceeded → RUNNER_RESOURCE_EXCEEDED
- [ ] Add error context to UI (user-friendly messages)
- [ ] Add retry logic for transient K8s Job creation failures
- [ ] Write integration tests for failure paths

**PRD Mapping:** NFR-REL1-REL2, Section 8.3-8.5

### P2.5 Observability (NFR-OPS1-OPS3, Section 14)
- [ ] Implement structured JSON logging
  - Request ID, run ID, dataset ID, timing, validation outcomes
- [ ] Log runner submission details (container ID / Job name)
- [ ] Add /healthz endpoint (agent server)
- [ ] Add /readyz endpoint (optional, for K8s readiness probe)
- [ ] Document log schema in README
- [ ] Configure logging via environment variables

**PRD Mapping:** NFR-OPS1-OPS3, Section 14

### P2.6 Test Suite (Section 15)
- [ ] Organize tests/
  - tests/unit/ (validators, compilers, capsules)
  - tests/integration/ (executor, end-to-end)
  - tests/security/ (red team fixtures)
- [ ] Write unit tests (target: >80% coverage)
  - QueryPlan validation
  - SQL compilation
  - SQL policy validator
  - Dataset loader
  - Capsule CRUD
- [ ] Write integration tests
  - End-to-end: question → plan → runner → result (Docker mode)
  - End-to-end: question → plan → runner → result (K8s mode)
  - Timeout enforcement
  - Concurrent runs
- [ ] Write security tests
  - Prompt injection attempts
  - SQL escape attempts
  - Data exfil attempts
  - Infinite/expensive queries
- [ ] Set up CI (GitHub Actions)
  - Run tests on PR
  - Lint code (ruff, black)
  - Build Docker images
  - Push images to GHCR on main branch

**PRD Mapping:** Section 15, Deployment-E

**Deliverable:** K8s deployment works via Helm chart, tests pass in CI

---

## Phase 3: Polish & Deployment (Day 5)

### P3.1 Documentation (Deployment-F)
- [ ] Write README.md
  - [ ] Overview (what is this, why it exists)
  - [ ] Architecture diagram
  - [ ] Quickstart (Local)
    - Prerequisites (Docker, docker-compose)
    - `make dev`
    - Open UI (http://localhost:3000)
    - Run 3 canned prompts
  - [ ] Quickstart (Local Kubernetes)
    - Prerequisites (kind/k3d, kubectl, helm)
    - `make k8s-up`
    - `make helm-install`
    - Test with prompts
  - [ ] Deploy Online
    - Hosting decision matrix (from Deployment PRD)
    - Default path: k3s on VM or managed K8s
    - Step-by-step runbook
    - TLS setup (Let's Encrypt or manual)
  - [ ] Security Model
    - Sandboxing approach
    - Validation gates
    - RBAC model
    - Network policies
  - [ ] Development
    - Project structure
    - How to add a dataset
    - How to extend the query DSL
  - [ ] Troubleshooting
    - Docker daemon not running
    - Image pull errors
    - RBAC permission denied
    - Jobs stuck in Pending
    - Runner timeouts
  - [ ] Testing
    - How to run tests
    - How to run smoke tests
  - [ ] License (MIT or Apache 2.0)
- [ ] Write CONTRIBUTING.md (optional, for polish)
- [ ] Write CHANGELOG.md (track versions)

**PRD Mapping:** Deployment-F

### P3.2 Hosting Deployment (FR-HOST-1, Deployment-D)
- [ ] Choose hosting path (k3s on VM or managed K8s)
- [ ] Create hosting runbook (docs/hosting.md)
  - Provision cluster/VM
  - Push images to registry
  - Configure Helm values (image tags, ingress host, TLS)
  - Install chart
  - Verify with smoke test
  - Teardown steps
- [ ] Execute deployment to get public URL
- [ ] Test public URL end-to-end
- [ ] Document public URL in README

**PRD Mapping:** FR-HOST-1, Deployment-D

### P3.3 CI/CD Pipeline (FR-CICD-1-3)
- [ ] Set up GitHub Actions workflow
  - [ ] Build UI image
  - [ ] Build agent-server image
  - [ ] Build runner image
  - [ ] Push images to GHCR (on main, tagged with commit SHA + 'latest')
- [ ] Add Makefile target: `make release TAG=v1.0`
  - Builds images with tag
  - Pushes to registry
  - Prints Helm install command
- [ ] Test CI/CD pipeline end-to-end

**PRD Mapping:** FR-CICD-1-3, Deployment-E

### P3.4 Polish & UX Improvements
- [ ] Improve error messages in UI (user-friendly)
- [ ] Add "suggested refinements" for common errors (missing limit, etc.)
- [ ] Add loading states and spinners
- [ ] Add result table pagination (if >200 rows message)
- [ ] Add ability to download run capsule JSON
- [ ] Add ability to share run capsule link (if hosted)
- [ ] (Stretch) Add simple charts for numeric results

**PRD Mapping:** Section 17 (Phase 3), Section 2.2

### P3.5 Acceptance Testing (Section 16)
- [ ] Verify all MVP acceptance criteria
  - [ ] UI loads, dataset selector works, prompts show
  - [ ] User asks a question → gets correct table result within 3s
  - [ ] JSON plan is shown and valid
  - [ ] SQL shown and validated
  - [ ] Execution happens only in sandbox runner
  - [ ] Runner has no network + read-only data + resource limits
  - [ ] Kubernetes mode works via Helm install and creates Jobs per run
  - [ ] Capsules stored and retrievable by run_id
  - [ ] At least 12 curated prompts (4 per dataset) all succeed
- [ ] Run smoke tests (local, K8s, online)
- [ ] Run security tests
- [ ] Run load test (5 concurrent users, 10 concurrent runs)
- [ ] Document any known issues or limitations

**PRD Mapping:** Section 16

**Deliverable:** Public URL live, README complete, all tests pass, 12+ prompts work

---

## Phase 4: Stretch Goals (Optional)

### P4.1 Restricted Python Execution (Section 2.2)
- [ ] Design Python execution mode schema (PythonPlan JSON)
- [ ] Implement Python sandbox runner
  - [ ] Restricted imports (pandas, numpy, no network libs)
  - [ ] AST validation (no imports of blocked modules, no file I/O)
  - [ ] Execute in sandbox (same security context as SQL runner)
- [ ] Add agent tool: execute_python_plan()
- [ ] Update UI to show Python code
- [ ] Write tests for Python mode
- [ ] Document Python mode in README (disabled by default)

**PRD Mapping:** Section 2.2, stretch goal

### P4.2 Simple Chart Output (Section 2.2)
- [ ] Add chart rendering to UI (bar/line charts)
- [ ] Detect numeric result columns
- [ ] Auto-generate chart if suitable
- [ ] Add "Download chart" button

**PRD Mapping:** Section 2.2, stretch goal

### P4.3 Query Caching (Section 2.2)
- [ ] Implement query result cache (Redis or in-memory)
- [ ] Cache key: dataset_version_hash + compiled_sql
- [ ] Add cache hit/miss metrics to logs
- [ ] Add cache TTL configuration

**PRD Mapping:** Section 2.2, stretch goal

### P4.4 Multi-turn Analysis Sessions (Section 2.2)
- [ ] Support temporary views (CREATE TEMP VIEW)
- [ ] Support derived tables across turns
- [ ] Add session persistence (per thread_id)
- [ ] Add "Reset session" button in UI

**PRD Mapping:** Section 2.2, stretch goal

---

## Risks & Mitigation Tracking

| Risk | Impact | Probability | Mitigation | Status |
|------|--------|-------------|------------|--------|
| LangChain UI integration complexity | High | Medium | Use stock UI, minimal customization | [ ] |
| SQL validation bypass | High | Low | Denylist + runner hardening + no-write policies | [ ] |
| K8s RBAC too broad | Medium | Low | Namespace-scoped Role; only Jobs/Pods | [ ] |
| Model generates wrong plan | Medium | Medium | Structured output + retry with validation feedback | [ ] |
| K8s Job latency too high | Medium | Low | Start with Docker, optimize later | [ ] |
| Dataset changes require rebuilds | Low | High | Accept for MVP, document evolution path | [ ] |

---

## Definitions & Glossary

- **Dataset**: Named group of CSV files with fixed schema
- **Query Plan (JSON DSL)**: Structured, validated representation of intended analysis
- **Compiled SQL**: Deterministic SQL generated from plan
- **Run Capsule**: Immutable record of inputs/outputs/logs/metadata
- **Runner**: Isolated execution environment for SQL/Python
- **Agent Server**: Receives chat messages, calls LLM, validates, schedules runs, returns results
- **Executor**: Backend abstraction for running sandboxed queries (Docker or K8s)

---

## Key Decisions Log

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| TBD | Default hosting path | Choose k3s VM vs managed K8s | Pending |
| TBD | SQL validation approach | Denylist vs AST parsing | Pending |
| TBD | Dataset mounting strategy | Bake into image vs ConfigMap vs PVC | Pending (recommend: bake) |
| TBD | Python stretch goal priority | Include in MVP or defer | Pending |

---

## Notes

- This TODO list is a living document; update status as work progresses
- Each checkbox maps to specific PRD requirements (noted in parentheses)
- Phases are ordered for low-risk, incremental delivery
- MVP acceptance criteria must all pass before considering stretch goals
- Target timeline: 5 days for MVP, +2 days for stretch goals
