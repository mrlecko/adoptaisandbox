# Runner

Sandboxed SQL execution environment using DuckDB.

## Purpose

The runner is a minimal, hardened Python script that:
1. Reads `RunnerRequest` JSON from stdin
2. Loads CSV files into DuckDB
3. Executes SQL query with timeout
4. Returns `RunnerResponse` JSON to stdout

## Security

The runner is designed to run in a highly restricted environment:

**Docker:**
- `--network none` (no network access)
- `--read-only` (read-only root filesystem)
- `--pids-limit 64` (process limit)
- `--memory 512m --cpus 0.5` (resource limits)
- Non-root user (UID 1000)

**Kubernetes:**
- Same restrictions via Pod security context
- NetworkPolicy denies egress
- RBAC limits agent to Job creation only

## Structure

```
runner/
├── runner.py       # Main execution script
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
  "sql": "SELECT * FROM orders LIMIT 10",
  "timeout_seconds": 10,
  "max_rows": 200
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
  "dataset_id": "test",
  "files": [{"name": "test.csv", "path": "/tmp/test.csv"}],
  "sql": "SELECT 1 as value",
  "timeout_seconds": 5,
  "max_rows": 10
}' | docker run -i --rm csv-analyst-runner:latest

# Test with security restrictions
docker run -i --rm \
  --network none \
  --read-only \
  --pids-limit 64 \
  --memory 512m \
  --cpus 0.5 \
  csv-analyst-runner:latest < request.json
```

## Dependencies

- Python 3.11+
- DuckDB
- No external network libraries

Minimal attack surface by design.
