# CSV Analyst Chat

An LLM-powered chat interface for analyzing CSV datasets with sandboxed SQL execution.

## Overview

CSV Analyst Chat enables natural language querying of CSV datasets through an intelligent agent that:
- Generates structured query plans (JSON DSL) or SQL from user questions
- Validates and compiles queries safely
- Executes queries in isolated sandboxed environments (Docker or Kubernetes)
- Returns results with full execution transparency and audit trails

## Current Implementation Status (2026-02-02)

Implemented now:
- ✅ Dataset generation + registry (`datasets/` + `datasets/registry.json`)
- ✅ QueryPlan DSL + deterministic compiler (`agent-server/app/models/query_plan.py`, `agent-server/app/validators/compiler.py`)
- ✅ Sandboxed DuckDB runner (`runner/runner.py`, `runner/Dockerfile`)
- ✅ Runner integration tests (`tests/integration/test_runner_container.py`)

Still in progress:
- 🚧 SQL policy validator for raw SQL
- 🚧 Docker/K8s executors in agent-server
- 🚧 FastAPI agent endpoints, run capsule persistence, and UI integration

**Key Features:**
- 🤖 LangChain-powered conversational agent
- 🔒 Sandboxed execution with strict security controls
- 📊 Multiple curated datasets with example prompts
- 🎯 Structured query planning with deterministic SQL compilation
- 🔍 Full execution transparency (query plans, SQL, logs, metadata)
- ☸️ Kubernetes deployment path planned (Helm + Job-based runner)

## Architecture

```
┌─────────────┐
│   Browser   │
│     UI      │
└──────┬──────┘
       │ HTTP
       v
┌─────────────────────┐
│   Agent Server      │
│  (FastAPI + Agent)  │
│  - Dataset APIs     │
│  - Chat endpoint    │
│  - Run orchestration│
└──────┬──────────────┘
       │ Executor API
       v
┌─────────────────────┐      ┌──────────────────┐
│   Executor Layer    │─────>│  Sandboxed       │
│  - DockerExecutor   │      │  SQL Runner      │
│  - K8sJobExecutor   │      │  (DuckDB)        │
└─────────────────────┘      └──────────────────┘
```

**Components:**
- **UI**: Chat interface (LangChain Agent UI starter)
- **Agent Server**: FastAPI backend with LangChain agent
- **Runner**: Isolated SQL execution environment (DuckDB in Docker/K8s); executes SQL only (no QueryPlan DSL parsing)
- **Datasets**: Versioned CSV datasets with metadata

## Quick Start (Current, Runnable Scope)

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Node.js 18+ (needed when UI integration is enabled)
- Make

### Validate QueryPlan + Runner

```bash
# Run QueryPlan unit tests
make test-unit

# Build runner image + execute containerized integration tests
make test-runner

# Optional: inspect QueryPlan DSL demos
cd agent-server && python3 demo_query_plan.py
```

## Kubernetes Path (Planned)

### Prerequisites
- kubectl
- Helm 3
- A Kubernetes cluster (kind, k3d, or cloud provider)

### Deploy to Kubernetes

```bash
# Create local cluster (optional)
make k8s-up

# Install via Helm
make helm-install

# Test deployment (pending implementation)
make k8s-smoke

# Access the application
kubectl port-forward svc/csv-analyst-ui 3000:80
```

## Project Structure

```
.
├── agent-server/       # QueryPlan DSL + compiler (FastAPI agent pending)
│   ├── app/
│   │   ├── models/     # Pydantic models (QueryPlan DSL)
│   │   └── validators/ # QueryPlan -> SQL compiler
│   └── requirements.txt
├── datasets/           # CSV datasets and metadata
│   ├── registry.json   # Dataset catalog
│   ├── ecommerce/      # Dataset A
│   ├── support/        # Dataset B
│   └── sensors/        # Dataset C
├── runner/             # Sandboxed SQL execution
│   ├── runner.py
│   └── Dockerfile
├── ui/                 # Frontend scaffold (pending)
├── helm/               # Helm chart scaffold (pending)
├── tests/              # Test suite
│   ├── unit/
│   ├── integration/
│   └── security/
├── docs/               # Documentation and PRDs
├── .github/            # CI/CD workflows
├── Makefile            # Common tasks
└── README.md
```

## Security Model

CSV Analyst Chat implements defense-in-depth security:

1. **SQL Validation**
   - Denylist for dangerous operations (DROP, DELETE, INSERT, etc.)
   - Allowlist mode for SELECT queries only
   - Query plan validation before compilation

2. **Sandboxed Execution**
   - Network isolation (`--network none` in Docker)
   - Read-only root filesystem
   - Resource limits (CPU, memory, PIDs)
   - Non-root user execution
   - Temporary filesystem restrictions
   - CSV load hardening (`/data`-scoped absolute paths + safe table-name validation)

3. **Kubernetes Security**
   - Pod Security Standards
   - Network policies (deny egress)
   - RBAC with minimal permissions
   - Security contexts enforced

4. **Output Controls**
   - Row limits (default 200)
   - Output size limits (64KB)
   - Data exfiltration heuristics

## Configuration

Key environment variables:

```bash
# Agent Server
ANTHROPIC_API_KEY=sk-ant-xxx    # Required
EXECUTION_MODE=docker           # docker or k8s
RUNNER_TIMEOUT=10               # Query timeout (seconds)
RUNNER_MAX_ROWS=200             # Max rows returned
LOG_LEVEL=info

# Kubernetes Mode
K8S_NAMESPACE=default
RUNNER_IMAGE=ghcr.io/user/csv-analyst-runner:latest
```

See `helm/csv-analyst-chat/values.yaml` for full configuration options.

## Development

### Adding a Dataset

1. Create a directory in `datasets/<dataset-name>/`
2. Add CSV files
3. Update `datasets/registry.json` with metadata
4. Add 4-6 example prompts
5. Run dataset validation: `make validate-datasets`

### Running Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests
make test-integration

# Runner container integration tests
make test-runner

# Security tests (red team)
make test-security

# Coverage report
make coverage
```

### CI/CD

GitHub Actions automatically:
- Run tests on PRs
- Build Docker images
- Push to GHCR on main branch
- Tag releases with semantic versioning

## Deployment

Deployment runbooks are still in progress. Current validated path is container-level runner testing via `make test-runner`.

## Troubleshooting

**Common Issues:**

1. **Runner timeout**
   - Increase `RUNNER_TIMEOUT` in config
   - Check query complexity

2. **RBAC permission denied (K8s)**
   - Verify ServiceAccount has Job creation permissions
   - Check namespace matches

3. **Dataset not loading**
   - Verify `datasets/registry.json` syntax
   - Check file paths are correct

## Roadmap

**Phase 0: Bootstrap & Planning** ✅ Complete
- [x] Project structure and documentation
- [x] PRD documents (Core + Deployment)
- [x] Use case specifications
- [x] Architecture decisions

**Phase 1: Foundations** 🚧 In Progress
- [x] Dataset generation & registry (FR-D1, FR-D2, FR-D3)
- [x] Query plan JSON DSL (FR-Q1, FR-Q2, FR-Q3)
- [x] Runner (SQL mode) (FR-X1-X4)
- [x] Runner integration tests (`make test-runner`)
- [ ] SQL validation (FR-SQL1, FR-SQL2, FR-SQL3)
- [ ] Docker executor (local mode)
- [ ] Agent server core
- [ ] Run capsule storage
- [ ] UI integration

**Phase 2: Production Shape** ⏭️ Pending
- [ ] Kubernetes Job executor
- [ ] Helm chart
- [ ] Security hardening
- [ ] Reliability & error handling
- [ ] Observability
- [ ] Test suite

**Phase 3: Polish & Deployment** ⏭️ Pending
- [ ] Documentation
- [ ] Hosting deployment
- [ ] CI/CD pipeline
- [ ] Polish & UX improvements
- [ ] Acceptance testing

**Stretch Goals** 🔮 Future
- [ ] MicroSandbox integration (alternative runner with mature sandboxing)
- [ ] Restricted Python execution mode (ideal use case for MicroSandbox)
- [ ] Chart visualization
- [ ] Query caching
- [ ] Multi-turn analysis sessions
- [ ] More datasets
- [ ] Abstract Runner interface for pluggable execution backends

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Built with:
- [LangChain](https://langchain.com) - Agent framework
- [DuckDB](https://duckdb.org) - Embedded SQL engine
- [FastAPI](https://fastapi.tiangolo.com) - Backend framework
- [LangChain Agent UI](https://github.com/langchain-ai/agent-ui) - Frontend starter

---

**Status:** 🚧 Active Development

For questions or issues, please open a GitHub issue.
