# Quick Start Guide

Get the CSV Analyst Chat project up and running quickly.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Git

## Setup (5 minutes)

### 1. Clone and Install Dependencies

```bash
# Install Python dependencies for agent server
cd agent-server
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

### 2. Generate Datasets

```bash
# Generate all datasets (deterministic)
python3 scripts/generate_ecommerce_dataset.py
python3 scripts/generate_support_dataset.py
python3 scripts/generate_sensors_dataset.py

# Create registry with metadata
python3 scripts/generate_registry.py

# Validate (optional)
python3 scripts/validate_datasets.py
```

This creates ~70K rows of sample data in `datasets/`.

### 3. Verify Setup

```bash
# Run tests
pytest tests/unit/ -v

# Should see: 66 passed
```

### 4. Try QueryPlan DSL

```bash
cd agent-server
python3 demo_query_plan.py
```

Shows 7 demos of the QueryPlan DSL in action.

## What You Can Do Now

### Create Query Plans

```python
from app.models.query_plan import QueryPlan, Filter, FilterOperator, SelectColumn
from app.validators.compiler import QueryPlanCompiler

# Create a query
plan = QueryPlan(
    dataset_id="ecommerce",
    table="orders",
    select=[SelectColumn(column="order_id"), SelectColumn(column="total")],
    filters=[Filter(column="status", op=FilterOperator.EQ, value="completed")],
    limit=10
)

# Compile to SQL
compiler = QueryPlanCompiler()
sql = compiler.compile(plan)
print(sql)
```

### Explore Datasets

```bash
# View dataset metadata
cat datasets/registry.json | jq '.datasets[] | {id, name, row_count}'

# Peek at data
head -n 20 datasets/ecommerce/orders.csv
head -n 20 datasets/support/tickets.csv
head -n 20 datasets/sensors/sensors.csv
```

### Run Tests

```bash
# All tests
pytest tests/unit/ -v

# Specific test file
pytest tests/unit/test_query_plan.py -v

# With coverage
pytest tests/unit/ --cov=app.models --cov=app.validators
```

## Next Steps

The project is currently at Phase 1.2 (QueryPlan DSL complete).

**Next components to build**:
1. **Runner** - DuckDB execution in sandbox ← You are here
2. **SQL Validator** - Validate raw SQL queries
3. **Docker Executor** - Run queries in Docker containers
4. **Agent Server** - LangChain agent with FastAPI
5. **UI** - Chat interface

See `TODO.md` for detailed task list.

## Common Commands

```bash
# Generate datasets
make validate-datasets  # (once Makefile targets are implemented)

# Run tests
make test-unit

# Run demo
cd agent-server && python3 demo_query_plan.py

# Check status
pytest tests/unit/ -q  # Quick test run
```

## Troubleshooting

**Issue**: Tests not found
```bash
# Make sure you're in project root
cd /path/to/adoptaisandbox
pytest tests/unit/ -v
```

**Issue**: Import errors
```bash
# Ensure agent-server dependencies installed
cd agent-server
pip install -r requirements.txt
```

**Issue**: Dataset generation fails
```bash
# Check Python version (need 3.11+)
python3 --version

# Run individual generators
python3 scripts/generate_ecommerce_dataset.py
```

## Project Structure

```
adoptaisandbox/
├── agent-server/          # Backend (FastAPI + LangChain)
│   ├── app/
│   │   ├── models/        # QueryPlan DSL ✅
│   │   └── validators/    # SQL compiler ✅
│   └── demo_query_plan.py # Demo script ✅
├── datasets/              # CSV datasets ✅
│   ├── ecommerce/
│   ├── support/
│   ├── sensors/
│   └── registry.json
├── runner/                # SQL executor (next)
├── tests/                 # Test suite ✅
│   └── unit/
├── docs/                  # Documentation ✅
└── scripts/               # Dataset generators ✅
```

## Resources

- **README.md** - Main project documentation
- **CLAUDE.md** - AI assistant context (development guide)
- **TODO.md** - Task breakdown and progress
- **docs/PROJECT_STATUS.md** - Current status report
- **docs/use-cases/** - Dataset specifications
- **agent-server/README.md** - QueryPlan DSL guide

## Getting Help

1. Check `CLAUDE.md` for development patterns
2. Review `TODO.md` for task context
3. Read component READMEs in each directory
4. Run demo scripts to see examples

Happy coding! 🚀
