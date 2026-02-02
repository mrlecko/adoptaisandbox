# Agent Server

FastAPI backend with LangChain agent for CSV analysis.

## Structure

```
agent-server/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration and settings
│   ├── agent/               # LangChain agent logic
│   │   ├── __init__.py
│   │   ├── graph.py         # Agent graph definition
│   │   ├── tools.py         # Agent tools
│   │   └── prompts.py       # System prompts
│   ├── executors/           # Execution backends
│   │   ├── __init__.py
│   │   ├── base.py          # Executor interface
│   │   ├── docker_executor.py
│   │   └── k8s_executor.py
│   ├── models/              # Pydantic models
│   │   ├── __init__.py
│   │   ├── query_plan.py    # QueryPlan DSL schema
│   │   ├── runner.py        # Runner request/response
│   │   └── capsule.py       # Run capsule schema
│   ├── validators/          # Validation logic
│   │   ├── __init__.py
│   │   ├── plan_validator.py
│   │   ├── sql_validator.py
│   │   └── compiler.py      # QueryPlan → SQL compiler
│   ├── api/                 # API routes
│   │   ├── __init__.py
│   │   ├── datasets.py
│   │   ├── chat.py
│   │   └── runs.py
│   └── storage/             # Capsule persistence
│       ├── __init__.py
│       └── capsules.py
├── Dockerfile
├── requirements.txt
└── README.md (this file)
```

## Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run server (development)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest ../tests/unit/
```

## Environment Variables

See `.env.example` at project root.

Key variables:
- `ANTHROPIC_API_KEY`: Required for LLM access
- `EXECUTION_MODE`: `docker` or `k8s`
- `RUNNER_IMAGE`: Docker image for SQL runner

## API Endpoints

- `GET /` - Health check
- `GET /datasets` - List available datasets
- `GET /datasets/{id}/schema` - Get dataset schema
- `POST /chat` - Chat with agent
- `POST /runs` - Submit query for execution
- `GET /runs/{run_id}` - Get run capsule

## Dependencies

Core:
- FastAPI - Web framework
- LangChain - Agent orchestration
- Pydantic - Data validation
- Uvicorn - ASGI server

Execution:
- Docker SDK - For Docker executor
- Kubernetes client - For K8s executor

Storage:
- SQLite (via Python stdlib) - Capsule storage
