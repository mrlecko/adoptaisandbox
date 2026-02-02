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

## Working with Datasets

### Generating Datasets

All datasets are **deterministically generated** using seeded random:

```bash
# Generate individual datasets
python3 scripts/generate_ecommerce_dataset.py    # Seed: 42
python3 scripts/generate_support_dataset.py      # Seed: 43
python3 scripts/generate_sensors_dataset.py      # Seed: 44

# Generate registry with version hashes
python3 scripts/generate_registry.py

# Validate datasets
python3 scripts/validate_datasets.py
```

**Location**: `datasets/`
- `ecommerce/` - 3 files, 13,526 rows
- `support/` - 1 file, 6,417 rows
- `sensors/` - 1 file, 49,950 rows
- `registry.json` - Metadata catalog

**Key Points**:
- Same seeds = identical data every time
- Version hashes (SHA256) ensure reproducibility
- Datasets are small (~5MB total)
- Ready to be baked into runner Docker image

### Dataset Registry

The registry (`datasets/registry.json`) contains:
- Dataset metadata (ID, name, description)
- Full schemas with column types
- 6 suggested prompts per dataset (18 total)
- SHA256 version hashes
- Foreign key relationships

Load registry in Python:
```python
import json
with open('datasets/registry.json') as f:
    registry = json.load(f)
```

## Working with QueryPlan DSL

### Creating Query Plans

```python
from app.models.query_plan import (
    QueryPlan, Filter, FilterOperator,
    Aggregation, AggregationFunction,
    SelectColumn, OrderBy, SortDirection
)
from app.validators.compiler import QueryPlanCompiler

# Example: Top products by revenue
plan = QueryPlan(
    dataset_id="ecommerce",
    table="order_items",
    select=[
        SelectColumn(column="product_id"),
        Aggregation(func=AggregationFunction.SUM, column="price", alias="revenue")
    ],
    group_by=["product_id"],
    order_by=[OrderBy(expr="revenue", direction=SortDirection.DESC)],
    limit=10
)

# Compile to SQL
compiler = QueryPlanCompiler()
sql = compiler.compile(plan)
```

### Running QueryPlan Demo

```bash
cd agent-server
python3 demo_query_plan.py
```

Shows 7 demos covering all features.

### QueryPlan Key Points

- **Validated**: Pydantic catches errors before SQL generation
- **Deterministic**: Same plan = same SQL
- **Secure**: Identifier validation, value escaping, exfil detection
- **Extensible**: QueryRequest supports future query types (Python, JSON)
- **DuckDB-optimized**: Generated SQL works with DuckDB

### Filter Operators

- `=`, `!=`, `<`, `<=`, `>`, `>=` - Comparison
- `in` - List membership
- `between` - Range [low, high]
- `contains`, `startswith`, `endswith` - String patterns (LIKE)
- `is_null`, `is_not_null` - NULL checks

### Aggregations

- `count`, `count_distinct`, `sum`, `avg`, `min`, `max`

## Testing

### Running Tests

```bash
# All unit tests (66 tests)
pytest tests/unit/ -v

# QueryPlan model tests (36 tests)
pytest tests/unit/test_query_plan.py -v

# Compiler tests (30 tests)
pytest tests/unit/test_compiler.py -v

# With coverage
pytest tests/unit/ --cov=app.models --cov=app.validators --cov-report=html

# Quick run
pytest tests/unit/ -q
```

### Test Organization

```
tests/
├── unit/
│   ├── test_query_plan.py    # Model validation tests
│   └── test_compiler.py       # SQL compilation tests
├── integration/               # (Future) End-to-end tests
└── security/                  # (Future) Red team tests
```

### Test Coverage

**Current**: 66 tests, 100% pass rate
- Filter validation (9 tests)
- SelectColumn validation (3 tests)
- Aggregation validation (1 test)
- QueryPlan validation (12 tests)
- QueryRequest validation (8 tests)
- SQL compilation (18 tests)
- Security features (4 tests)
- Golden queries (3 tests)
- Complex scenarios (8 tests)

## Development Commands

### Common Tasks

```bash
# Generate datasets
python3 scripts/generate_ecommerce_dataset.py
python3 scripts/generate_support_dataset.py
python3 scripts/generate_sensors_dataset.py
python3 scripts/generate_registry.py

# Validate datasets
python3 scripts/validate_datasets.py

# Run tests
pytest tests/unit/ -v

# Run demo
cd agent-server && python3 demo_query_plan.py

# Future: Start development environment
make dev

# Future: Run smoke tests
make smoke
```

### Makefile Commands

The Makefile contains 30+ commands. Key ones:

```bash
make help          # Show all commands
make install       # Install dependencies
make dev           # Start local environment (future)
make test          # Run all tests
make test-unit     # Unit tests only
make lint          # Run linters
make format        # Auto-format code
make k8s-up        # Create local K8s cluster
make helm-install  # Deploy via Helm
make clean         # Clean build artifacts
```

## Current Project Status

**Completed (✅)**:
- Phase 0.1: Project bootstrap, PRDs, decisions
- Phase 1.1: Dataset generation, registry, validation
- Phase 1.2: QueryPlan DSL, SQL compiler, tests

**In Progress (🚧)**:
- Phase 1.4: Runner (DuckDB in sandbox) - NEXT

**Pending (⏭️)**:
- Phase 1.3: SQL validator (denylist)
- Phase 1.5: Docker executor
- Phase 1.6: Agent server core
- Phase 1.7: Run capsule storage
- Phase 1.8: UI integration

See `TODO.md` for detailed task breakdown.

## Important File Locations

**Datasets**:
- `datasets/` - CSV files
- `datasets/registry.json` - Metadata catalog
- `scripts/generate_*_dataset.py` - Generators

**QueryPlan DSL**:
- `agent-server/app/models/query_plan.py` - Models
- `agent-server/app/validators/compiler.py` - SQL compiler
- `agent-server/demo_query_plan.py` - Demo script

**Tests**:
- `tests/unit/test_query_plan.py` - Model tests
- `tests/unit/test_compiler.py` - Compiler tests

**Documentation**:
- `README.md` - Main project docs
- `CLAUDE.md` - This file (AI assistant context)
- `CHANGELOG.md` - Version history
- `TODO.md` - Task tracking
- `CONTRIBUTING.md` - Contribution guidelines
- `docs/DECISIONS.md` - Architecture decisions
- `docs/use-cases/` - Dataset specifications
- `agent-server/README.md` - QueryPlan docs

## Session Handoff Checklist

When starting a new session:
1. Read TODO.md to understand current phase and status
2. Check CHANGELOG.md for recent changes
3. Review relevant PRD sections for context
4. Check git status for uncommitted work
5. Run `pytest tests/unit/ -q` to verify tests pass
6. Ask user for current priority if unclear

When ending a session:
1. Update TODO.md with task status
2. Add entry to CHANGELOG.md if significant changes made
3. Update CLAUDE.md with new guidance (commands, file locations, etc.)
4. Run tests to ensure nothing broken
5. Commit work with descriptive message
6. Note any blockers or next steps in TODO.md
7. Update this file if major architecture decisions made

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
