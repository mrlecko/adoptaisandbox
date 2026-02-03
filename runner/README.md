# Runner

Sandboxed SQL and Python execution environment.

## Purpose

The runner image provides two entrypoints:
1. `runner.py` (SQL mode): loads CSVs into DuckDB and executes SQL
2. `runner_python.py` (Python mode): loads CSVs into pandas DataFrames and executes restricted Python

Both entrypoints read `RunnerRequest` JSON from stdin and return `RunnerResponse` JSON on stdout.

QueryPlan DSL creation/validation/compilation stays upstream in `agent-server`.

## Security

The runner is designed to run in a highly restricted environment:

**Docker:**
- `--network none` (no network access)
- `--read-only` (read-only root filesystem)
- `--pids-limit 64` (process limit)
- `--memory 512m --cpus 0.5` (resource limits)
- Non-root user (UID 1000)
- CSV path validation (`/data` absolute paths only)
- Table-name sanitization for loaded CSV files

**Kubernetes:**
- Same restrictions via Pod security context
- NetworkPolicy denies egress
- RBAC limits agent to Job creation only

## Structure

```
runner/
├── common.py       # Shared sanitization + response helpers
├── runner.py       # Main execution script
├── runner_python.py # Restricted Python entrypoint
├── Dockerfile      # Minimal image with DuckDB
└── README.md       # This file
```

## RunnerRequest Schema

```json
{
  "dataset_id": "ecommerce",
  "files": [
    {"name": "orders.csv", "path": "/data/ecommerce/orders.csv"}
  ],
  "query_type": "sql",
  "sql": "SELECT * FROM orders LIMIT 10",
  "python_code": null,
  "timeout_seconds": 10,
  "max_rows": 200,
  "max_output_bytes": 65536
}
```

## RunnerResponse Schema

```json
{
  "status": "success",  // or "error", "timeout"
  "columns": ["order_id", "total"],
  "rows": [[1, 100.50], [2, 75.25]],
  "row_count": 2,
  "exec_time_ms": 45,
  "stdout_trunc": "",
  "stderr_trunc": "",
  "error": null
}
```

## Local Testing

```bash
# Build image
docker build -t csv-analyst-runner:latest .

# Test with sample input
echo '{
  "dataset_id": "support",
  "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
  "sql": "SELECT COUNT(*) AS n FROM tickets",
  "timeout_seconds": 5,
  "max_rows": 10
}' | docker run -i --rm -v ../datasets:/data:ro csv-analyst-runner:latest

# Test SQL with security restrictions
docker run -i --rm \
  --network none \
  --read-only \
  --pids-limit 64 \
  --memory 512m \
  --cpus 0.5 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v ../datasets:/data:ro \
  csv-analyst-runner:latest < request.json

# Test Python entrypoint from same image
echo '{
  "dataset_id": "support",
  "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
  "python_code": "result_df = tickets.groupby(\"priority\").size().reset_index(name=\"n\")",
  "timeout_seconds": 5,
  "max_rows": 10,
  "max_output_bytes": 65536
}' | docker run -i --rm --entrypoint python3 -v ../datasets:/data:ro csv-analyst-runner:latest /app/runner_python.py
```

From repository root you can run the full runner integration suite:

```bash
make test-runner
```

## Dependencies

- Python 3.11+
- DuckDB, pandas, numpy
- No external network libraries in runtime policy

Minimal attack surface by design.
