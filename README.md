# CSV Analyst Chat

An LLM-powered chat interface for analyzing CSV datasets with sandboxed SQL execution.

## Overview

CSV Analyst Chat enables natural language querying of CSV datasets through an intelligent agent that:
- Generates structured query plans (JSON DSL) or SQL from user questions
- Validates and compiles queries safely
- Executes queries in isolated sandboxed environments (Docker or Kubernetes)
- Returns results with full execution transparency and audit trails

**Key Features:**
- 🤖 LangChain-powered conversational agent
- 🔒 Sandboxed execution with strict security controls
- 📊 Multiple curated datasets with example prompts
- 🎯 Structured query planning with deterministic SQL compilation
- 🔍 Full execution transparency (query plans, SQL, logs, metadata)
- ☸️ Kubernetes-ready with Helm charts for production deployment

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
- **Runner**: Isolated SQL execution environment (DuckDB in Docker/K8s)
- **Datasets**: Versioned CSV datasets with metadata

## Quick Start (Local Development)

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Node.js 18+ (for UI)
- Make

### Run Locally

```bash
# Start all services
make dev

# Access the UI
open http://localhost:3000
```

Try these example prompts:
- "Show me top 10 orders by total amount"
- "What's the average CSAT score by ticket priority?"
- "Which sensors had anomalies in the last 24 hours?"

### Development Setup

```bash
# Install Python dependencies (agent server)
cd agent-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install UI dependencies
cd ui
npm install

# Run tests
make test

# Run security tests
make test-security
```

## Quick Start (Kubernetes)

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

# Test deployment
make k8s-smoke

# Access the application
kubectl port-forward svc/csv-analyst-ui 3000:80
```

## Project Structure

```
.
├── agent-server/       # FastAPI backend + LangChain agent
│   ├── app/
│   │   ├── agent/      # Agent graph and tools
│   │   ├── executors/  # Docker/K8s execution backends
│   │   ├── models/     # Pydantic models (QueryPlan, etc.)
│   │   └── validators/ # SQL and plan validation
│   ├── Dockerfile
│   └── requirements.txt
├── datasets/           # CSV datasets and metadata
│   ├── registry.json   # Dataset catalog
│   ├── ecommerce/      # Dataset A
│   ├── support/        # Dataset B
│   └── sensors/        # Dataset C
├── runner/             # Sandboxed SQL execution
│   ├── runner.py
│   └── Dockerfile
├── ui/                 # Frontend (LangChain Agent UI)
├── helm/               # Kubernetes Helm charts
│   └── csv-analyst-chat/
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

See [docs/hosting.md](docs/hosting.md) for detailed deployment guides:
- Local development (Docker Compose)
- Local Kubernetes (kind/k3d)
- Cloud Kubernetes (GKE, EKS, AKS)
- Bare metal k3s

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

See [docs/troubleshooting.md](docs/troubleshooting.md) for more.

## Roadmap

**MVP (Current)**
- [x] Core agent with JSON query DSL
- [x] SQL validation and sandboxing
- [x] Docker and K8s execution modes
- [x] 3 curated datasets
- [ ] Production hosting
- [ ] CI/CD pipeline

**Stretch Goals**
- [ ] Restricted Python execution mode
- [ ] Chart visualization
- [ ] Query caching
- [ ] Multi-turn analysis sessions
- [ ] More datasets

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
