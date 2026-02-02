# Agent Server

FastAPI backend with LangChain agent for CSV Analyst Chat.

## QueryPlan DSL (Completed ✅)

The QueryPlan DSL is a structured, validated JSON representation for queries.

### Features

✅ **Pydantic Models** - Full type safety and validation
✅ **SQL Compiler** - Deterministic QueryPlan → SQL compilation
✅ **Extensible Design** - Ready for future query types (Python, JSON queries)
✅ **Security** - Data exfiltration heuristics, SQL injection prevention
✅ **Comprehensive Tests** - 66 tests covering models and compiler
✅ **DuckDB Compatible** - Generated SQL works with DuckDB

### Quick Start

```python
from app.models.query_plan import QueryPlan, Filter, FilterOperator, SelectColumn
from app.validators.compiler import QueryPlanCompiler

# Create a query plan
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
# Output:
# SELECT
#   "order_id",
#   "total"
# FROM "orders"
# WHERE
#   "status" = 'completed'
# LIMIT 10
```

### Supported Operations

**Filter Operators**:
- Comparison: `=`, `!=`, `<`, `<=`, `>`, `>=`
- List: `in`, `between`
- Pattern: `contains`, `startswith`, `endswith`
- NULL: `is_null`, `is_not_null`

**Aggregations**:
- `count`, `count_distinct`, `sum`, `avg`, `min`, `max`

**Other**:
- GROUP BY (required when mixing columns with aggregations)
- ORDER BY (multiple columns supported)
- LIMIT (enforced, default 200, max 1000)

### Example Queries

**1. Simple SELECT with filters**
```python
QueryPlan(
    dataset_id="ecommerce",
    table="orders",
    filters=[
        Filter(column="status", op="=", value="completed"),
        Filter(column="total", op=">", value=100)
    ],
    order_by=[OrderBy(expr="total", direction="desc")],
    limit=10
)
```

**2. Aggregation with GROUP BY**
```python
QueryPlan(
    dataset_id="ecommerce",
    table="order_items",
    select=[
        SelectColumn(column="category"),
        Aggregation(func="sum", column="price", alias="total_revenue")
    ],
    group_by=["category"],
    order_by=[OrderBy(expr="total_revenue", direction="desc")]
)
```

**3. Complex filters**
```python
QueryPlan(
    dataset_id="support",
    table="tickets",
    filters=[
        Filter(column="priority", op="in", value=["High", "Critical"]),
        Filter(column="csat_score", op="is_null"),
        Filter(column="created_at", op=">=", value="2024-01-01")
    ]
)
```

### Running Tests

```bash
# All tests (66 tests)
pytest tests/unit/test_query_plan.py tests/unit/test_compiler.py -v

# Model validation tests (36 tests)
pytest tests/unit/test_query_plan.py -v

# Compiler tests (30 tests)
pytest tests/unit/test_compiler.py -v

# With coverage
pytest tests/unit/ --cov=app.models --cov=app.validators --cov-report=html
```

### Running Demo

```bash
cd agent-server
python3 demo_query_plan.py
```

Shows 7 demos:
1. Simple SELECT with filters
2. Aggregation with GROUP BY
3. Complex filters (IN, BETWEEN, NULL)
4. String pattern matching (LIKE)
5. QueryRequest envelope (extensible)
6. Data exfiltration detection
7. Golden query example

## Future Extensibility

The QueryRequest envelope supports multiple query types:

```python
class QueryType(str, Enum):
    PLAN = "plan"           # ✅ Implemented
    SQL = "sql"             # ✅ Implemented (validation TBD)
    PYTHON = "python"       # 🔮 Future
    JSON_QUERY = "json_query"  # 🔮 Future
```

**Future query types**:
- **Python**: Sandboxed Python execution (pandas, numpy)
- **JSON Query**: Custom JSON-based query language
- **GraphQL**: If needed for complex data traversal

Adding a new query type requires:
1. Add enum value to `QueryType`
2. Add field to `QueryRequest` model
3. Update validation logic
4. Implement executor/compiler

## Structure (Current)

```
agent-server/
├── app/
│   ├── models/
│   │   ├── __init__.py
│   │   └── query_plan.py      ✅ QueryPlan DSL models
│   ├── validators/
│   │   ├── __init__.py
│   │   └── compiler.py         ✅ QueryPlan → SQL compiler
│   ├── agent/                  🔜 LangChain agent (next)
│   ├── executors/              🔜 Docker/K8s executors
│   ├── api/                    🔜 FastAPI routes
│   └── storage/                🔜 Capsule persistence
├── demo_query_plan.py          ✅ Demo script
├── requirements.txt            ✅ Dependencies
└── README.md                   ✅ This file
```

## Next Steps

With QueryPlan DSL complete, next steps are:

1. **SQL Validator** - Validate raw SQL queries (denylist)
2. **Runner** - DuckDB execution in sandbox
3. **Executors** - DockerExecutor and K8sJobExecutor
4. **Agent** - LangChain agent with tools
5. **API** - FastAPI endpoints
6. **Capsule Storage** - SQLite persistence

See `TODO.md` (Phase 1.2+) for detailed breakdown.

## Testing Strategy

**Unit Tests** (✅ Complete):
- Model validation (all edge cases)
- SQL compilation correctness
- Security (escaping, injection prevention)
- Determinism (same plan = same SQL)

**Integration Tests** (🔜 Next):
- End-to-end: QueryPlan → SQL → DuckDB → Results
- Golden queries from use case specs
- Real dataset testing

**Security Tests** (🔜 Next):
- SQL injection attempts
- Data exfiltration attempts
- Prompt injection resilience
