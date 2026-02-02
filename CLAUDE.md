# CLAUDE.md - Context for AI Assistants

This file provides essential context for Claude (or other AI assistants) working on this project across multiple sessions.

## Project Identity

**Name:** CSV Analyst Chat
**Type:** LLM-powered data analysis application
**Stage:** Active Development (MVP in progress)
**Primary Goal:** Enable natural language querying of CSV datasets with secure, sandboxed SQL execution

## Core Architecture

```
User Chat → LangChain Agent → Query Plan/SQL → Sandboxed Runner (Docker/K8s) → Results
```

**Key Components:**
1. **Agent Server** (FastAPI + LangChain): Receives chat messages, generates query plans or SQL
2. **Runner** (DuckDB): Executes SQL in isolated sandbox with strict security controls
3. **Executor Layer**: Abstracts Docker vs K8s backend for running queries
4. **UI** (LangChain Agent UI): Chat interface with dataset selection and result visualization

## Tech Stack

**Backend:**
- Python 3.11+
- FastAPI (web framework)
- LangChain (agent orchestration)
- DuckDB (SQL engine)
- Pydantic (data validation)

**Frontend:**
- LangChain Agent UI starter (React/Next.js)

**Infrastructure:**
- Docker (local sandboxing)
- Kubernetes (production execution)
- Helm (K8s packaging)

**Model:**
- Claude (Anthropic) via LangChain integration

## Key Design Principles

1. **Security First**: Queries execute in isolated sandboxes with no network, read-only data, resource limits
2. **Transparency**: Every run produces a "capsule" with full audit trail (plan, SQL, logs, metadata)
3. **Structured by Default**: Agent generates JSON QueryPlan DSL, compiled to deterministic SQL
4. **Validation Gates**: Multi-layer validation (plan schema, SQL policy, runner security)
5. **Local + Cloud Ready**: Works with Docker Compose locally, Helm on K8s for production

## File Organization

```
agent-server/    → FastAPI backend, agent logic, executors, validators
datasets/        → CSV files + registry.json with metadata
runner/          → Isolated SQL runner (DuckDB) with security hardening
ui/              → Frontend (LangChain Agent UI starter)
helm/            → Kubernetes Helm charts
tests/           → Unit, integration, security tests
docs/            → PRDs, implementation plans, runbooks
```

**Important Files:**
- `TODO.md`: Master task list with phases and acceptance criteria
- `docs/IMPLEMENTATION_PLAN.md`: Detailed implementation strategy
- `docs/PRD/`: Product requirements documents
- `datasets/registry.json`: Dataset catalog (not yet created)
- `Makefile`: Common development tasks

## Development Workflow

**Standard Commands (via Makefile):**
- `make dev` → Start local environment (docker-compose)
- `make test` → Run full test suite
- `make k8s-up` → Create local K8s cluster
- `make helm-install` → Deploy to K8s via Helm

**Development Phases (see TODO.md):**
- Phase 0: Bootstrap & Planning (current)
- Phase 1: Foundations (datasets, query DSL, runner, agent)
- Phase 2: Production Shape (K8s, Helm, security hardening, tests)
- Phase 3: Polish & Deployment (docs, hosting, CI/CD)
- Phase 4: Stretch Goals (Python mode, charts, caching)

## Critical Context

### Query Flow
1. User sends natural language question via UI
2. Agent receives question + dataset context
3. Agent generates QueryPlan JSON (structured) OR raw SQL (if complex)
4. Server validates plan/SQL against security policies
5. Plan compiled to deterministic SQL
6. SQL submitted to Executor (Docker or K8s)
7. Runner executes query in sandbox, returns JSON result
8. Result + metadata stored in "run capsule"
9. UI displays result table + execution details

### Security Model
- **SQL Validation**: Denylist for dangerous operations (DROP, DELETE, etc.)
- **Sandbox**: No network, read-only data, resource limits (CPU, memory, PIDs)
- **K8s**: NetworkPolicy denies egress, RBAC limited to Job creation, Pod Security Standards enforced
- **Output Limits**: Max 200 rows, 64KB stdout/stderr
- **Data Exfil Heuristics**: Reject queries without LIMIT + many columns + no aggregation

### Dataset Strategy (MVP)
- 3 curated datasets (ecommerce, support tickets, sensors)
- Datasets baked into runner image (no dynamic mounting for MVP)
- Each dataset has 4-6 example prompts
- Version hashing (SHA256) for reproducibility

### Execution Modes
1. **Docker Mode** (local dev): Uses Docker SDK, creates containers per run
2. **K8s Mode** (production): Creates Kubernetes Jobs per run, polls for completion

## Common Tasks & Patterns

**When adding a new feature:**
1. Check TODO.md for alignment with phases
2. Read relevant PRD sections (in docs/PRD/)
3. Write tests first (TDD preferred)
4. Update CHANGELOG.md
5. Update README.md if user-facing

**When debugging:**
1. Check structured logs (JSON format)
2. Look for run_id in capsule storage
3. Verify runner security context
4. Check executor cleanup (orphaned containers/jobs)

**When working with LangChain:**
- Use structured outputs for QueryPlan generation
- Agent tools: list_datasets, get_schema, execute_query_plan, execute_sql, get_run_status
- System prompt emphasizes JSON plan as default, SQL as fallback
- Retry with validation feedback if plan invalid

## Known Constraints & Decisions

1. **Datasets baked into image** (not mounted dynamically) for MVP simplicity
2. **No streaming execution** for MVP (async job model instead)
3. **SQLite for capsule storage** (not PostgreSQL) for simplicity
4. **LangChain Agent UI starter** used as-is (minimal customization)
5. **Default row limit 200** to prevent accidental large exports
6. **DuckDB read-only mode** (CSVs loaded per query, no persistence)

## Integration Points

**LangChain:**
- Agent graph defined in `agent-server/app/agent/`
- Tools registered for dataset discovery and query execution
- Structured output via Pydantic models

**Docker SDK:**
- Used by DockerExecutor in `agent-server/app/executors/docker_executor.py`
- Creates containers with security flags, stdin/stdout communication

**Kubernetes Client:**
- Used by K8sJobExecutor in `agent-server/app/executors/k8s_job_executor.py`
- Creates Jobs, polls status, fetches logs, cleans up

## Testing Strategy

- **Unit Tests**: Validators, compilers, models (pytest)
- **Integration Tests**: End-to-end flows (Docker + K8s modes)
- **Security Tests**: Red team fixtures (SQL injection, prompt injection, data exfil)
- **Smoke Tests**: Quick health checks (make smoke)
- **Target Coverage**: >80% for core logic

## Common Pitfalls to Avoid

1. **Don't skip validation**: Always validate plans AND compiled SQL
2. **Don't trust LLM output**: Use structured outputs + retry loops
3. **Don't leak resources**: Always cleanup containers/jobs after runs
4. **Don't skip security contexts**: Verify runner restrictions in both Docker and K8s
5. **Don't hardcode timeouts**: Use config for flexibility
6. **Don't log sensitive data**: Redact API keys, sanitize user inputs in logs

## References

- **PRD**: See `docs/PRD/core_prd.md` and `docs/PRD/deployment_prd.md`
- **Implementation Plan**: See `docs/IMPLEMENTATION_PLAN.md`
- **Task List**: See `TODO.md`
- **LangChain Docs**: https://python.langchain.com/docs/
- **DuckDB Docs**: https://duckdb.org/docs/
- **FastAPI Docs**: https://fastapi.tiangolo.com/

## Session Handoff Checklist

When starting a new session:
1. Read TODO.md to understand current phase and status
2. Check CHANGELOG.md for recent changes
3. Review relevant PRD sections for context
4. Check git status for uncommitted work
5. Ask user for current priority if unclear

When ending a session:
1. Update TODO.md with task status
2. Add entry to CHANGELOG.md if significant changes made
3. Commit work with descriptive message
4. Note any blockers or next steps in TODO.md
5. Update this file if major architecture decisions made

## Questions to Ask User

If you need to make decisions, prefer asking about:
- **Deployment target**: Docker-only or K8s support needed?
- **Model selection**: Claude Sonnet vs Opus (cost vs capability tradeoff)
- **Dataset priority**: Which datasets to build first?
- **Security vs UX**: How strict should validation be?
- **Hosting plan**: Where will this be deployed? (affects infrastructure choices)

## Anthropic API Key Location

The project expects `ANTHROPIC_API_KEY` to be set via environment variable. For local development, use `.env` file (gitignored).

## Last Updated

2026-02-02 - Initial project bootstrap
